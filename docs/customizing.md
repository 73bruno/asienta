# Customizing

Asienta ships neutral: an indigo accent, the name "Asienta", generic categories. Everything that
was specific to the business it was built for is configuration.

## Brand

```ini
[brand]
name = Gestoría López          ; sidebar, browser tab, login screen
tagline = Client invoices     ; small line under the name
accent = #0F766E                ; one colour; hover, focus, soft backgrounds are derived from it
logo = assets/logo.svg          ; PNG or SVG, square works best (also used as the favicon)
```

The whole palette is CSS variables at the top of `asienta/web/app.css`. The accent drives every
tint through `color-mix()`, so one hex code is enough for a coherent result in light and dark mode.
Dark mode follows the operating system.

## Language

The interface is in Spanish and English and switches with one click (the choice is remembered per
browser). `[app] language` sets the default and the language the AI writes its notes in. Findings
are stored as codes, so switching language never needs a re-read.

To add a language: copy a block in `asienta/web/i18n.js` and in `asienta/i18n.py`.

## Presets and categories

The AI puts every invoice line in a category; each category maps to an expense account. That's
what sends the wine on a food wholesaler's invoice to the drinks account.

```ini
[app]
preset = hospitality          ; asienta/presets/hospitality.ini · retail.ini · services.ini

[categories]                  ; override or extend the preset's
food      = 600000100 | food, ingredients, sauces, condiments
drinks    = 600000200 | wine, beer, soft drinks, water, spirits, coffee and tea
packaging = 600000300 | bags, film, boxes and disposable cups bought to be used
cleaning  = 600000400 | cleaning products
```

The text after `|` is what the AI reads to classify, so write it the way you would explain it to a
new colleague. `other` always exists and goes to the supplier's main account.

```ini
[split]
only_prefixes = 600           ; split by category only when the main account starts like this
follow_main = packaging       ; categories that stay with the main account…
follow_when = food, drinks    ; …when the main account is one of these (crate deposits → drinks)
```

A preset is just an INI file with `[company] activity`, `[categories]` and `[split]`; point
`preset` at your own file path to share a setup between installations.

## Chart of accounts

```ini
[ledger]
supplier_prefixes = 400,410   ; which accounts are suppliers/creditors
expense_prefixes = 6,2        ; which accounts can receive the cost
suggest_prefixes = 6,21       ; which ones the AI may suggest for a supplier with no history
vat_filed_until = auto        ; auto · YYYY-MM · off

[accounts]
input_vat = 21:472000021, 10:472000010, 4:472000004     ; empty = found in the chart
withholding = 475100000
```

## The entry text

```ini
[export]
description = S/ FRA. [{number}] {supplier}     ; {number} {supplier} {date}
description_length = 25
```
