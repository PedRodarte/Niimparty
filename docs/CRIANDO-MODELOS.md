# Criando um modelo de etiqueta

Um modelo é **uma pasta** dentro de `templates/`, com um arquivo `template.yaml` e, se quiser, imagens. Não precisa programar.

```
templates/meu-modelo/
├─ template.yaml     # layout, textos padrão, campo do nome do convidado
├─ preview.png       # miniatura (gerada pelo `preview`)
├─ ornaments/        # enfeites em PNG preto e branco (fundo transparente)
└─ fonts/            # opcional: fontes .ttf/.otf só deste modelo
```

## Passo a passo

1. Copie a pasta de um modelo parecido com o que você quer, por exemplo `templates/basico` → `templates/formatura`.
2. Abra `templates/formatura/template.yaml` num editor de texto (Bloco de Notas serve) e mude o `name`, os textos e os enfeites.
3. Confira se está tudo certo:

   ```
   run.bat validate formatura          (Windows)
   make validate                       (macOS/Linux)
   python niimparty.py validate formatura
   ```

4. Veja como ficou:

   ```
   run.bat preview formatura
   run.bat preview formatura --photo C:\fotos\teste.jpg
   ```

   As etiquetas de exemplo vão para a pasta `previews/` em vários tamanhos (50 × 80, 50 × 50, 50 × 30 e 12 × 40 mm), e a miniatura `preview.png` do modelo é atualizada.

5. Escolha o modelo com `run.bat setup` (ou, em breve, pelo `/admin`).

## Exemplo completo

```yaml
name: Formatura
description: Moldura simples com capelo
orientation: portrait          # portrait (em pé) | landscape (deitada)

photo:
  aspect: "4:5"                # 1:1 | 4:5 | 3:4 | 3:2 | 2:3 | full
  margin_mm: 2                 # espaço entre a borda da etiqueta e a foto
  corner_radius_mm: 2          # cantos arredondados da foto (0 = retos)
  border_mm: 0                 # contorno em volta da foto (0 = sem)

frame:                         # moldura em volta da etiqueta (opcional)
  style: solid                 # solid | double | dashed | dotted
  border_mm: 0.5               # espessura da linha
  inset_mm: 1                  # distância da borda
  corner_radius_mm: 2

texts:
  - id: title                  # nome interno, sem espaços
    label: Título              # como aparece nas perguntas e no /admin
    default: "Formatura {ano}"
    font: InterDisplay-Black
    size_mm: 4.5               # altura da letra maiúscula, em mm
    position: bottom           # top (acima da foto) | bottom (abaixo)
    align: center              # left | center | right
  - id: subtitle
    label: Turma
    default: "{evento}"
    font: InterDisplay-SemiBold
    size_mm: 2.6

guest_field:                   # nome do convidado (o organizador decide se pede)
  enabled: true
  label: Seu nome
  format: "parabéns, {nome}!"
  max_chars: 24
  size_mm: 2.5

ornaments:
  - file: ornaments/capelo.png
    position: photo-top-right  # veja a lista abaixo
    size_mm: 9                 # largura do enfeite
    offset_mm: [2, 2]          # empurra para dentro (x, y)

logo:                          # espaço para o logo do organizador (opcional)
  enabled: false
  position: top                # top | bottom
  height_mm: 8

example:                       # textos de exemplo para as prévias (sem dados reais!)
  event: Turma 2026
  guest: Convidado
```

## Variáveis

Use dentro de qualquer texto. Elas são preenchidas na hora da impressão:

| Variável | Vira |
| --- | --- |
| `{evento}` | nome do evento (pergunta da primeira execução) |
| `{data}` | data do evento, no formato do idioma (31/12/2026 ou 12/31/2026) |
| `{ano}` | ano do evento |
| `{nome}` | nome que o convidado digitou (só em `guest_field.format`) |

Se o convidado não digitar nada, a linha do nome simplesmente não aparece.

## Referência dos campos

### `photo`

| Campo | Padrão | O que faz |
| --- | --- | --- |
| `aspect` | `"4:5"` | proporção da foto (largura:altura); `full` ocupa o espaço que sobrar |
| `margin_mm` | `2` | margem em volta |
| `corner_radius_mm` | `0` | arredonda os cantos |
| `border_mm` | `0` | contorno em volta da foto |
| `max_share` | `0.68` | no modo paisagem, fração máxima da largura usada pela foto |

### `texts` (lista)

| Campo | Padrão | O que faz |
| --- | --- | --- |
| `id` | obrigatório | identificador único; o `config.yaml` usa para trocar o texto |
| `label` | o `id` | nome amigável do campo |
| `default` | vazio | texto padrão (aceita variáveis) |
| `font` | `InterDisplay-Bold` | nome do arquivo da fonte, sem `.ttf` |
| `size_mm` | `3.5` | altura da letra maiúscula em mm |
| `position` | `bottom` | `top` ou `bottom` |
| `align` | `center` | `left`, `center` ou `right` |
| `max_chars` | `40` | corta textos maiores |
| `max_lines` | `2` | quebra em até 2 linhas antes de diminuir a letra |
| `uppercase` | `false` | tudo em maiúsculas |
| `letter_spacing_mm` | `0` | espaço extra entre letras |

### `ornaments` (lista)

| Campo | Padrão | O que faz |
| --- | --- | --- |
| `file` | obrigatório | caminho do PNG dentro da pasta do modelo |
| `position` | `bottom-right` | `top-left`, `top-right`, `bottom-left`, `bottom-right`, `top`, `bottom`, `left`, `right` (cantos da etiqueta) ou `photo-top-left`, `photo-top-right`, `photo-bottom-left`, `photo-bottom-right` (centrado no canto da foto) |
| `size_mm` | `8` | largura |
| `offset_mm` | `[0, 0]` | desloca para dentro da etiqueta/foto |
| `rotate` | `0` | gira em graus (sentido anti-horário) |
| `flip` | — | `horizontal` ou `vertical` (espelha) |
| `layer` | `over` | `over` (por cima da foto) ou `under` (por baixo) |

Os enfeites nunca saem da etiqueta: se a posição ficar para fora, eles são empurrados para dentro.

### `frame` e `logo`

Veja o exemplo completo acima. O logo é enviado pelo organizador e convertido para preto e branco automaticamente.

### Etiquetas com moldura já impressa

Alguns rolos já vêm com moldura colorida e uma janela branca para a foto (ex.: 54 × 66 mm). Nesse caso, diga ao Niimparty onde fica cada coisa, em mm, a partir do canto de cima à esquerda, com a etiqueta em pé. O modelo `moldura-colorida-54x66` é um exemplo pronto.

```yaml
label_mm: [54, 66]                    # o modelo só serve para este tamanho
preprinted:
  window_mm: [5.8, 9.0, 42.4, 42.4]   # janela branca: [x, y, largura, altura]
  preview_colors: ["#F4C7C9"]         # cor do papel, só para a prévia na tela
photo:
  aspect: "1:1"
  box_mm: [6.4, 9.6, 41.2, 41.2]      # onde a foto é impressa
text_box_mm: [5, 52.4, 44, 12.6]      # onde vão os textos
max_rows: 2                           # da 2ª linha em diante, os textos se juntam com "·"
```

- Meça o seu rolo com uma régua: as medidas dos anúncios são aproximadas.
- Deixe a foto uns 0,5 mm para dentro da janela, porque o papel pode andar um pouco.
- A moldura colorida nunca é impressa. A cor aparece só na prévia do celular e na placa.
- O preto sai bem sobre cores claras, então dá para imprimir texto na faixa colorida.
- Se a etiqueta for mais larga que a cabeça de impressão (48 mm na B2 Pro), só a parte do meio recebe tinta, e o `validate` avisa se a foto ou o texto passarem disso.

## Fontes

As fontes em `assets/fonts/` valem para todos os modelos:

| Nome | Estilo |
| --- | --- |
| `InterDisplay-Regular`, `-Medium`, `-SemiBold`, `-Bold`, `-Black` | sem serifa, limpa |
| `DMSerifDisplay-Regular` | serifada, elegante |
| `LilitaOne-Regular` | arredondada, divertida |

Para usar outra fonte, coloque o arquivo `.ttf` ou `.otf` em `templates/<modelo>/fonts/` e use o nome do arquivo (sem a extensão) em `font`. Use só fontes com licença livre (por exemplo, as do [Google Fonts](https://fonts.google.com/)) e inclua o arquivo de licença junto.

## Enfeites (ornamentos)

- PNG com **fundo transparente**, só **preto e branco** (cinza vira preto ou branco na impressão).
- Partes **brancas** cobrem a foto; partes **transparentes** deixam a foto aparecer.
- Desenhe grande (uns 600 px) e com traços grossos: na etiqueta o enfeite tem poucos milímetros.
- SVG também funciona se o pacote opcional `cairosvg` estiver instalado (no Windows ele exige a biblioteca Cairo; PNG é mais simples).
- Só use imagens que você mesmo fez ou com licença livre.

## Regras de legibilidade (impressão térmica)

- Letra com **no mínimo 2,5 mm** de altura.
- Traços com **no mínimo 0,3 mm** (fontes muito finas somem).

O `validate` e o `/admin` avisam quando o modelo quebra essas regras. Os avisos não impedem o uso, mas a etiqueta pode sair ilegível.

## Como o modelo se adapta ao tamanho da etiqueta

O modelo é desenhado pensando numa etiqueta de 50 mm no lado curto. Em etiquetas menores:

- textos, enfeites e margens diminuem na mesma proporção, sem passar de 2,5 mm na letra quando dá;
- se o texto ocupar mais que 45% da altura, ele diminui para a foto caber;
- textos longos quebram em até 2 linhas antes de diminuir;
- modelos em paisagem viram retrato em etiquetas quase quadradas (como 50 × 50);
- em tiras compridas (como 12 × 40 mm) tudo fica deitado: foto à esquerda, título e uma linha de texto à direita, sem logo.

## Checklist antes de compartilhar um modelo

- [ ] `validate` sem erros
- [ ] prévias conferidas em pelo menos dois tamanhos
- [ ] nenhum nome de família, data real ou foto de pessoa nos arquivos
- [ ] fontes e imagens com licença livre (licença incluída na pasta)
