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

- **Modelos prontos:** básico, Natal, aniversário, casamento, chá de bebê e corporativo (com logo)
- **Crie seu modelo sem programar:** uma pasta com um arquivo `template.yaml` e as imagens
- Textos, data e nome do convidado configuráveis
- Etiquetas de vários tamanhos, em retrato ou paisagem
- Tratamento de foto pensado para impressão térmica (tons de cinza ou pontilhado)
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
| Outros modelos Niimbot | não testados: crie um perfil em `printers/profiles/` e conte como foi |
| Sem impressora | modo simulado (PNG) |

A comunicação com a impressora usa bibliotecas da comunidade [NiimBlue](https://printers.niim.blue/). Se o seu modelo não funcionar com elas, o modo manual gera a etiqueta pronta para você imprimir pelo app oficial.

## Requisitos

- Python 3.12+
- Computador com Bluetooth ou USB, na mesma rede Wi-Fi dos convidados
- Impressora Niimbot e etiquetas (papel fotográfico recomendado para fotos)

## Instalação

```bash
git clone https://github.com/<seu-usuario>/niimparty.git
cd niimparty
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

```bash
make run
```

Na primeira vez, o Niimparty pergunta o idioma, o nome e a data do evento, o modelo, os textos, se a etiqueta leva o nome do convidado, a impressora, o tamanho da etiqueta e o PIN do painel. Depois, tudo pode ser alterado em `http://<ip-do-computador>:8000/admin`.

```bash
make qr        # gera a placa A5 com os QR codes
make preview   # gera etiquetas de exemplo de todos os modelos
make test      # roda os testes
```

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
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make run
```

Printer communication relies on the community [NiimBlue](https://printers.niim.blue/) libraries. First tested model: Niimbot B2 Pro. Unofficial project, not affiliated with NIIMBOT. MIT licensed.
