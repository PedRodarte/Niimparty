# Niimparty — Especificação do projeto

> Documento de planejamento e fonte de verdade para o desenvolvimento.

## 1. Visão geral

O Niimparty é uma cabine de fotos por QR code para impressoras de etiqueta Niimbot, para qualquer tipo de festa ou evento. O convidado escaneia um QR code, envia uma foto pelo próprio celular e, em segundos, ela sai impressa numa etiqueta com a moldura do evento.

**Princípios**

- **Genérico:** nenhum texto, data, nome ou tema fixo no código. Tudo vem de modelos e configuração.
- **Sem programar:** quem usa escolhe um modelo, preenche os textos e roda. Criar um modelo novo também não exige código.
- **Local e privado:** tudo roda num computador na rede do evento. Sem nuvem, sem cadastro e sem app.
- **Impressora trocável:** a B2 Pro é o primeiro modelo suportado. Outros modelos Niimbot entram por perfil.

**Um único fluxo:** QR code → página → upload → prévia → fila → impressão. Não existe modo cabine, segundo dispositivo nem câmera ao vivo.

**Fora do escopo:** e-mail, WhatsApp, impressão colorida e hospedagem em nuvem.

## 2. Experiência do convidado

Do QR à etiqueta em menos de 30 segundos, com no máximo 3 toques.

1. **Escanear:** uma placa ao lado da impressora traz dois QR codes, o do Wi-Fi e o da página.
2. **Abrir a página:** visual do modelo escolhido e dois botões grandes, "Tirar foto" (`<input type="file" accept="image/*" capture="environment">`) e "Escolher da galeria".
3. **Personalizar (opcional, se o modelo permitir):** campo "Seu nome" ou uma mensagem curta.
4. **Prévia:** a etiqueta exatamente como vai sair, com os botões "Imprimir" e "Trocar foto".
5. **Fila:** "Sua foto é a 3ª da fila", com atualização automática até "Saiu! Pegue na impressora".

**Regras de UX**

- Botões com no mínimo 56 px de altura e texto grande, porque o público pode incluir crianças e pessoas mais velhas.
- Sem cadastro, sem login, sem app.
- Erros em linguagem simples, por exemplo: "A impressora está sem papel, já avisamos o organizador".
- Limite de fotos por aparelho configurável (padrão: 3 a cada 10 minutos).
- Interface traduzível (arquivos de idioma), com português e inglês desde o início.

## 3. Arquitetura

Tudo roda num único computador na rede local.

```
Celular do convidado ──upload──▶ Servidor FastAPI ──▶ Pipeline de imagem ──▶ Renderizador de modelo ──▶ Fila (SQLite) ──▶ Driver ──▶ Impressora Niimbot
        ▲                              │                                                                                   (Mock | NiimBlue | Manual)
        └──────── status (SSE) ────────┘                                                                                   + perfil do modelo
Celular do organizador ──▶ /admin (PIN): modelo, textos, prévia, fila, reimprimir, apagar
```

- Só o driver e o perfil da impressora mudam entre simulação e impressão real, ou entre modelos de impressora.
- O renderizador recebe a foto tratada, o modelo e os textos, e devolve a etiqueta pronta na resolução da impressora.

## 4. Modelos de etiqueta

Um modelo é uma pasta em `templates/`, sem código Python. Quem quiser criar um modelo novo copia uma pasta e edita.

```
templates/natal/
├─ template.yaml     # layout, textos padrão, campos do convidado
├─ preview.png       # miniatura mostrada no /admin
├─ ornaments/        # PNG ou SVG em preto e branco
└─ fonts/            # opcional; senão usa as fontes padrão
```

**Exemplo de `template.yaml`**

```yaml
name: Natal
description: Moldura com flocos e estrelas
orientation: portrait          # portrait | landscape
photo:
  aspect: "4:5"                # 1:1 | 4:5 | 3:2 | full
  margin_mm: 2
texts:
  - id: title
    default: "Natal {ano}"
    font: InterDisplay-Black
    size_mm: 5
  - id: subtitle
    default: "Família Silva · {data}"
    font: InterDisplay-SemiBold
    size_mm: 3
guest_field:
  enabled: true
  label: "Seu nome"
  format: "com carinho, {nome}"
  max_chars: 24
ornaments:
  - file: ornaments/flocos.png
    position: bottom-left
  - file: ornaments/estrela.png
    position: bottom-right
```

- **Variáveis:** `{ano}`, `{data}`, `{nome}` e `{evento}` são preenchidas na hora.
- **Tamanho:** o modelo é descrito em milímetros e proporções, e o renderizador adapta ao tamanho de etiqueta configurado (ex.: 50 × 30, 50 × 50, 50 × 80 mm).
- **Modelos incluídos no repositório:** `basico` (só foto e uma linha de texto), `natal`, `aniversario`, `casamento`, `cha-de-bebe` e `corporativo` (com espaço para logo).
- **Logo próprio:** qualquer modelo pode aceitar uma imagem do organizador, convertida automaticamente para preto e branco.

**Regras de legibilidade para impressão térmica:** letra com no mínimo 2,5 mm de altura e traços de no mínimo 0,3 mm. O renderizador avisa no `/admin` se um modelo violar essas regras.

## 5. Processamento de imagem

Pipeline em Pillow + NumPy, igual para todos os modelos:

1. Corrigir rotação pela EXIF.
2. Converter HEIC e WebP para RGB (`pillow-heif`).
3. Recortar para a proporção do modelo, centralizado. Opcional: detecção de rosto com OpenCV.
4. Redimensionar para a resolução final com LANCZOS.
5. Escala de cinza, contraste local (CLAHE), gama de cerca de 0,8 e um leve unsharp mask. Valores ajustáveis por perfil de impressora e tipo de papel.
6. Saída conforme o papel:
    - **Fotográfico (tons de cinza):** 8 bits, se a impressora aceitar.
    - **Etiqueta comum:** pontilhado Atkinson ou Floyd–Steinberg em 1 bit.
7. Salvar o PNG final em `output/` com timestamp.

## 6. Impressoras

Cada modelo de impressora tem um perfil em `printers/profiles/`:

```yaml
# printers/profiles/b2_pro.yaml
model: Niimbot B2 Pro
dpi: 300
printhead_mm: 48
label_widths_mm: [20, 50]
density: { min: 1, max: 5, default: 3 }
grayscale: true            # aceita papel fotográfico
connection: [bluetooth, usb]
status: em teste
```

A comunicação fica atrás de uma interface `Printer` com três drivers:

| Driver | Como funciona | Quando usar |
| --- | --- | --- |
| `MockPrinter` | salva o PNG em `output/` e simula 5 s de impressão | sem impressora, testes, desenvolvimento |
| `NiimBluePrinter` | usa o servidor REST do niimblue-node (CLI da niimbluelib), por Bluetooth ou USB | impressão automática |
| `ManualPrinter` | envia o PNG pronto para uma pasta; alguém imprime pelo app Niimbot | quando o modelo não é suportado pelas bibliotecas |

A Niimbot não tem API oficial. A integração usa as bibliotecas da comunidade [NiimBlue](https://printers.niim.blue/other/third-party-software/), e o suporte varia por modelo. Por isso cada perfil tem um campo `status` (testado, em teste, não testado), e o README mostra essa tabela.

**Teste de viabilidade com a B2 Pro (primeiro modelo)**

- [ ] Conectar pelo niim.blue no Chrome e imprimir um texto simples.
- [ ] Imprimir uma foto em papel fotográfico e comparar cinza com pontilhado.
- [ ] Repetir por USB-C.
- [ ] Imprimir via REST pelo niimblue-node.

Se falhar: testar NiimPrintX e niimprint. Se nada funcionar, o `ManualPrinter` garante o uso.

## 7. Configuração

**Primeira execução:** se `config.yaml` não existir, `make run` faz perguntas no terminal e grava o arquivo:

- Idioma (pt-BR / en)
- Nome do evento e data
- Modelo (lista os disponíveis em `templates/`)
- Textos do modelo (mostra o padrão de cada campo)
- Pedir nome do convidado? (s/n)
- Impressora (perfil) e driver (mock / niimblue / manual)
- Tamanho da etiqueta e tipo de papel (fotográfico / comum)
- PIN do `/admin`

**Depois, no `/admin`:** trocar modelo e textos com prévia ao vivo, pausar e retomar a fila, reimprimir, apagar fotos e baixar todas as fotos do evento num `.zip`.

Segredos (PIN, senha do Wi-Fi para o QR) ficam em `.env`.

## 8. Rede, QR code e acesso

Padrão: só Wi-Fi local, com IP fixo (reserva DHCP no roteador). Opção documentada: 4G via Cloudflare Tunnel, que exige um domínio.

| Opção | Endereço no QR | Precisa de |
| --- | --- | --- |
| Wi-Fi local (padrão) | `http://192.168.x.y:8000` | IP fixo |
| 4G + Wi-Fi | `https://subdominio.seudominio` | domínio no Cloudflare + Cloudflare Tunnel |

- Sem câmera ao vivo, não é preciso HTTPS na rede local.
- O QR usa o IP, não `.local`, porque mDNS falha em vários Androids.
- `make qr` gera uma placa A5 em PDF com o QR do Wi-Fi (`WIFI:T:WPA;S:<rede>;P:<senha>;;`), o QR da página e o visual do modelo escolhido.
- **Segurança:** fotos de até 15 MB, só imagens (validar o conteúdo, não a extensão), limite por IP e `/admin` com PIN. Com túnel, exigir um código curto impresso na placa.

## 9. Estrutura do repositório e stack

Repositório público `niimparty`, licença MIT, Python 3.12.

| Camada | Escolha |
| --- | --- |
| Servidor | FastAPI + Uvicorn |
| Imagem | Pillow, pillow-heif, NumPy, OpenCV (opcional) |
| Fila | `asyncio.Queue` + SQLite |
| Impressora | interface `Printer` + drivers + perfis YAML |
| Frontend | HTML + CSS + JS vanilla, sem build |
| Config | `config.yaml` + `.env` |
| Idiomas | arquivos JSON em `locales/` |
| Testes | pytest |

```
niimparty/
├─ app/
│  ├─ main.py             # rotas: /, /upload, /status/{id}, /admin
│  ├─ setup_wizard.py     # perguntas da primeira execução
│  ├─ queue.py            # fila + SQLite
│  ├─ imaging.py          # pipeline da foto
│  ├─ renderer.py         # aplica o modelo e gera a etiqueta
│  └─ printers/
│     ├─ base.py
│     ├─ mock.py
│     ├─ niimblue.py
│     └─ manual.py
├─ printers/profiles/     # b2_pro.yaml, ...
├─ templates/             # basico/, natal/, aniversario/, casamento/, cha-de-bebe/, corporativo/
├─ locales/               # pt-BR.json, en.json
├─ web/                   # index.html, admin.html, style.css, app.js
├─ assets/fonts/          # fontes padrão (licença livre)
├─ tools/
│  ├─ make_qr.py          # placa A5 com QR codes
│  ├─ preview.py          # gera etiquetas de exemplo de todos os modelos
│  └─ validate_template.py
├─ tests/
├─ docs/
│  ├─ PROJETO.md          # este arquivo
│  └─ CRIANDO-MODELOS.md  # guia para criar um modelo novo
├─ output/                # gitignored
├─ uploads/               # gitignored
├─ config.example.yaml
├─ .env.example
├─ Makefile               # make run | make qr | make preview | make test
├─ LICENSE
└─ README.md
```

Fotos, `config.yaml` e `.env` nunca vão para o Git. Nenhum dado pessoal (nomes de família, datas reais) entra nos modelos de exemplo.

## 10. Roadmap

1. **Fase 1 — MVP simulado:** página, upload, pipeline, renderizador com o modelo `basico`, fila, `MockPrinter`, assistente de primeira execução. Pronto quando: celular no Wi-Fi → PNG em `output/` em menos de 5 s.
2. **Fase 2 — modelos:** formato `template.yaml`, os seis modelos de exemplo, `tools/preview.py`, `tools/validate_template.py` e `docs/CRIANDO-MODELOS.md`.
3. **Fase 3 — impressão real:** teste de viabilidade com a B2 Pro, `NiimBluePrinter` ou `ManualPrinter`, perfil `b2_pro.yaml` e calibração em papel fotográfico e comum.
4. **Fase 4 — acabamento:** `/admin` com prévia ao vivo, placa A5, download das fotos em `.zip`, mensagens de erro, idioma inglês e teste de carga com 20 fotos seguidas.
5. **Fase 5 — publicação:** README com GIF de demonstração, tabela de impressoras suportadas, guia de contribuição e primeira release.

**Checklist para o dia do evento** (vai no README)

- [ ] Computador na tomada, sem suspensão nem atualizações automáticas
- [ ] Impressora carregada e conectada (USB se possível), com rolo reserva
- [ ] `make run` rodando e `/admin` aberto no celular do organizador
- [ ] Placa com QR codes testada num iPhone e num Android
- [ ] Wi-Fi com sinal forte perto da placa
- [ ] Etiqueta de teste impressa antes do primeiro convidado

## 11. Decisões em aberto

| Decisão | Padrão até decidir |
| --- | --- |
| Sistemas operacionais suportados | Windows, macOS e Linux |
| Tamanho de etiqueta padrão | 50 × 80 mm, retrato |
| Só Wi-Fi ou também 4G | só Wi-Fi; túnel documentado como opcional |
| Uma ou duas cópias por foto | configurável, padrão uma |
| Driver padrão | Mock até o teste com a B2 Pro |
| Guardar originais | sim, em `uploads/`, apagáveis pelo `/admin` |
