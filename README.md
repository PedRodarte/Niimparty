# Niimparty

**Cabine de fotos por QR code para impressoras de etiqueta Niimbot.**
Os convidados escaneiam um QR code, enviam uma foto pelo celular e ela sai impressa na hora, numa etiqueta com a moldura da sua festa. Serve para aniversário, casamento, Natal, chá de bebê, evento de empresa ou o que você inventar.

> 🇺🇸 [English below](#english)

> ⚠️ Projeto independente e não oficial. Não tem relação com a NIIMBOT.

---

## Como funciona

1. Você escolhe um modelo, preenche os textos do evento e roda o Niimparty.
2. Imprime uma placa com dois QR codes: o do Wi-Fi e o da página.
3. O convidado escaneia, tira ou escolhe uma foto e toca em **Imprimir**.
4. O Niimparty ajusta a foto, monta a etiqueta e manda para a impressora. O celular mostra a posição na fila e avisa quando a foto saiu.

Sem app, sem cadastro, sem nuvem. Tudo roda num computador na sua rede.

## Recursos

- **Modelos prontos:** básico, Natal, aniversário, casamento, chá de bebê, corporativo (com logo) e moldura colorida (para rolos com moldura já impressa, ex.: 54 × 66 mm)
- **Crie seu modelo sem programar:** uma pasta com um arquivo `template.yaml` e as imagens
- Textos, data e nome do convidado configuráveis
- Etiquetas de vários tamanhos, em retrato ou paisagem
- Tratamento de foto pensado para impressão térmica: no papel fotográfico, tons de cinza de verdade (16 tons por ponto, sem retícula); no papel comum, pontilhado
- Página leve com botões grandes, que funciona em qualquer celular
- Prévia da etiqueta antes de imprimir e fila com status em tempo real
- Painel `/admin` com PIN: trocar modelo e textos com prévia ao vivo, pausar a fila, reimprimir, baixar todas as fotos
- Gerador de placa A5 com os QR codes
- Português e inglês
- Modo simulado: gera as etiquetas como PNG, sem impressora

## Impressoras

| Modelo | Status |
| --- | --- |
| Niimbot B2 Pro | em teste |
| Niimbot D110M | não testado (perfil inicial para etiquetas 12 × 40 mm, só preto e branco) |
| Outros modelos Niimbot | não testados: crie um perfil em `printers/profiles/` e conte como foi |
| Sem impressora | modo simulado (PNG) |

A comunicação com a impressora usa bibliotecas da comunidade [NiimBlue](https://printers.niim.blue/). Se o seu modelo não funcionar com elas, o modo manual gera a etiqueta pronta para você imprimir pelo app oficial.

## Requisitos

- Python 3.12+ (o 3.11 também funciona)
- Windows, macOS ou Linux
- Computador com Bluetooth ou USB, na mesma rede Wi-Fi dos convidados
- Impressora Niimbot e etiquetas (papel fotográfico recomendado para fotos)

## Instalação

```bash
git clone https://github.com/<seu-usuario>/niimparty.git
cd niimparty
```

**Windows:** não precisa instalar nada além do Python. Dê dois cliques em `run.bat` ou rode no terminal:

```bat
run.bat
```

Na primeira vez ele cria o ambiente `.venv` e instala as dependências sozinho.

**macOS / Linux (ou Windows com `make`):**

```bash
make run
```

## Uso

Na primeira vez, o Niimparty pergunta o idioma, o nome e a data do evento, o modelo, os textos, se a etiqueta leva o nome do convidado, a impressora, o tamanho da etiqueta, o tipo de papel e o PIN do painel. Ele grava as respostas em `config.yaml` e o PIN em `.env`. Para refazer as perguntas: `run.bat setup` ou `make setup`.

Depois, o terminal mostra o endereço para abrir no celular (por exemplo `http://192.168.1.5:8000`). No Windows, na primeira vez, aceite o aviso do Firewall para **redes privadas**, senão os celulares não conseguem abrir a página.

| Windows | make | Python direto | O que faz |
| --- | --- | --- | --- |
| `run.bat` | `make run` | `python niimparty.py run` | inicia a cabine |
| `run.bat setup` | `make setup` | `python niimparty.py setup` | refaz as perguntas |
| `run.bat qr` | `make qr` | `python niimparty.py qr` | gera a placa A5 com os QR codes |
| `run.bat preview` | `make preview` | `python niimparty.py preview` | gera etiquetas de exemplo de todos os modelos |
| `run.bat validate` | `make validate` | `python niimparty.py validate` | confere os modelos (erros e legibilidade) |
| `run.bat test` | `make test` | `python niimparty.py test` | roda os testes |

Enquanto a impressora não chega, use o modo `mock`: cada etiqueta vira um PNG em `output/`.

### Painel do organizador (`/admin`)

Abra `http://<ip-do-computador>:8000/admin` no navegador do computador ou do celular (Android ou iPhone, no mesmo Wi-Fi) e digite o PIN. Não precisa instalar nada.

- **Etiqueta:** escolha o modelo, mude o nome do evento, a data e os textos e veja a prévia ao vivo. Dá para testar com uma foto sua, que não é guardada nem impressa. Ao tocar em **Salvar**, os próximos convidados já recebem a etiqueta nova, sem reiniciar.
- **Fila:** pause e retome a impressão, reimprima ou apague uma foto.
- **Fotos:** baixe todas as fotos e etiquetas num `.zip` ou apague tudo depois do evento.

As alterações ficam no `config.yaml`, só no seu computador. Depois de 5 PINs errados, o painel bloqueia por 1 minuto.

### Placa com os QR codes

`run.bat qr` (ou `make qr`) gera `output/placa-qr.pdf`, uma folha A5 com o nome do evento, uma etiqueta de exemplo e dois QR codes: um conecta o celular ao Wi-Fi e o outro abre a página. Na primeira vez ele pergunta o nome e a senha do Wi-Fi e guarda no `.env`. Opções úteis:

```bat
run.bat qr --url http://192.168.0.50:8000   & rem endereço fixo (reserva de IP no roteador)
run.bat qr --no-wifi                        & rem só o QR da página
```

O PDF contém a senha do Wi-Fi, por isso fica em `output/`, que nunca vai para o Git.

## Criando um modelo

Copie uma pasta de `templates/`, edite o `template.yaml` e troque os ornamentos. O guia completo está em [`docs/CRIANDO-MODELOS.md`](docs/CRIANDO-MODELOS.md).

```yaml
name: Aniversário
orientation: portrait
photo: { aspect: "4:5" }
texts:
  - { id: title, default: "{evento}", size_mm: 5 }
  - { id: subtitle, default: "{data}", size_mm: 3 }
guest_field: { enabled: true, format: "com carinho, {nome}" }
```

## Dicas para o dia do evento

- [ ] Computador na tomada, sem suspensão nem atualizações automáticas
- [ ] Impressora carregada e conectada (USB se possível), com rolo reserva
- [ ] IP fixo para o computador no roteador
- [ ] Placa com QR codes testada num iPhone e num Android
- [ ] Etiqueta de teste impressa antes de os convidados chegarem

## Privacidade

As fotos ficam só no computador que roda o Niimparty, nas pastas `uploads/` e `output/`, que nunca vão para o Git. Apague tudo pelo `/admin` depois do evento se não quiser guardar.

## Estado do desenvolvimento

| Fase | Situação |
| --- | --- |
| 1. MVP simulado (página, upload, pipeline, modelo `basico`, fila, `MockPrinter`, assistente) | pronta |
| 2. Seis modelos de exemplo, `preview`, `validate` e guia de modelos | pronta (aguardando aprovação do visual) |
| 3. Impressão real (`NiimBluePrinter` / `ManualPrinter`) e calibração dos 16 tons de cinza | aguardando a impressora |
| 4. Painel `/admin` (prévia ao vivo, fila, `.zip`), placa A5 | pronta; falta o teste de carga com 20 fotos |

### Decisões adotadas

Padrões da seção "Decisões em aberto" de [`docs/PROJETO.md`](docs/PROJETO.md), até alguém decidir diferente:

- **Sistemas:** Windows, macOS e Linux (`run.bat` no Windows, `Makefile` nos outros, `niimparty.py` em todos).
- **Etiqueta padrão:** 50 × 80 mm, retrato.
- **Rede:** só Wi-Fi local; o túnel para 4G fica documentado como opcional.
- **Cópias por foto:** uma (configurável em `copies`).
- **Painel:** a sessão dura 12 horas; o idioma, a impressora e o driver continuam no `run.bat setup`, porque trocar a impressora no meio do evento exige reiniciar.
- **Driver padrão:** `mock`, até o teste com a impressora real.
- **Originais:** guardados em `uploads/`, apagáveis pelo `/admin`.
- **Limite por aparelho:** conta as fotos *enviadas para impressão* por IP (padrão 3 a cada 10 minutos); só a prévia não conta.
- **Falha da impressora** (sem papel, desligada): a fila pausa sozinha, a foto continua em primeiro lugar e o convidado vê a mensagem; o organizador retoma pelo `/admin`.
- **Etiquetas pequenas:** textos, enfeites e margens encolhem junto com a etiqueta; tiras compridas (ex.: 12 × 40 mm) ficam deitadas, com no máximo 2 linhas de texto e sem logo.
- **Papel fotográfico:** as Niimbot com modo cinza (B2 Pro, B21 Pro) aquecem cada ponto em 16 intensidades, então a foto vai em 16 tons de cinza, sem pontilhado. A curva de tons ainda será calibrada com uma etiqueta de teste na impressora real.
- **Rolos com moldura já impressa:** a moldura nunca é impressa, só a foto na janela e o texto na faixa; as medidas do modelo `moldura-colorida-54x66` vieram da foto do anúncio e serão conferidas com régua no rolo de verdade.
- **Ornamentos em SVG** precisam do pacote opcional `cairosvg` (no Windows ele exige a biblioteca Cairo); PNG funciona sempre.

## Contribuindo

Modelos novos, perfis de impressoras e traduções são muito bem-vindos. A especificação do projeto está em [`docs/PROJETO.md`](docs/PROJETO.md).

## Licença

MIT

---

## English

**QR-code photo booth for Niimbot label printers.** Guests scan a QR code, send a photo from their phone, and it prints right away on a label with your party's frame: birthdays, weddings, Christmas, baby showers, corporate events, anything.

- Ready-made templates, plus your own templates without coding (a folder with a `template.yaml`).
- No app, no sign-up, no cloud: everything runs on one computer on your local network.
- Thermal-friendly image processing, live queue status, PIN-protected `/admin` with live preview.
- Portuguese and English. Simulated mode generates PNG labels without a printer.

```bash
git clone https://github.com/<your-user>/niimparty.git
cd niimparty
make run          # Windows: run.bat
```

Printer communication relies on the community [NiimBlue](https://printers.niim.blue/) libraries. First tested model: Niimbot B2 Pro. Unofficial project, not affiliated with NIIMBOT. MIT licensed.
