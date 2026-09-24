<div align="center">

<img src="asienta/web/favicon.svg" width="72" alt="">

# Asienta

Lee facturas de proveedores con un LLM y las convierte en asientos contables,<br>
exportados en el formato de importación de tu programa de contabilidad.

[![CI](https://github.com/73bruno/asienta/actions/workflows/ci.yml/badge.svg)](https://github.com/73bruno/asienta/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Dependencias](https://img.shields.io/badge/dependencias-0-16A34A)
![Licencia](https://img.shields.io/badge/licencia-MIT-4F46E5)

<img src="docs/media/demo.gif" width="100%" alt="Un ticket llega por correo, se lee, se corrige un NIF en un clic, se reparte por cuentas y se exporta">

<sub>La demo, con datos ficticios · [MP4](docs/media/demo.mp4) · [English](README.md)</sub>

</div>

## Qué hace

1. Recoge facturas (PDF y fotos) de un buzón de correo, una carpeta, el navegador o una API HTTP.
2. Manda cada una a un LLM que extrae proveedor, NIF, número, fecha, líneas e IVA a un esquema JSON fijo.
3. Propone el asiento a partir de tu contabilidad: cuenta del proveedor, cuentas de gasto, reparto de líneas y fecha contable.
4. Pasa comprobaciones: dígito de control del NIF, totales, IVA por tipo, duplicados y trimestres de IVA cerrados.
5. Cuando una persona lo aprueba, genera un fichero de importación para el programa de contabilidad.

El LLM solo hace el paso 2. Los pasos 3 y 4 son Python determinista: cada propuesta se puede rastrear y probar, y el modelo se puede cambiar sin tocarlos.

## Qué incluye

- **Entradas**: buzón IMAP (con reenvíos y logos de firma), carpeta vigilada, arrastrar y soltar, cámara del móvil y API HTTP.
- **Proveedores de LLM**: Gemini (por defecto), Claude, OpenAI, cualquier endpoint compatible con OpenAI (Mistral, OpenRouter, Azure…) y modelos locales con Ollama, LM Studio o vLLM.
- **Fuentes de contabilidad** (solo lectura): ficheros CSV, la exportación de cuentas de Sage 50 / ContaPlus o conexión en vivo al SQL Server de Sage 50.
- **Formatos de exportación**: Sage 50 (XDIARIO), CSV y JSON. ContaPlus, el importador Excel de Sage 50, a3ASESOR, Holded, Xero y QuickBooks Online están hechos según sus especificaciones publicadas y tienen tests, pero aún no se han importado en los programas reales (beta).
- **Reglas fiscales**: España (dígito de control de NIF/NIE/CIF, IVA, retención de IRPF, recargo de equivalencia, abonos y trimestres presentados).
- **Interfaz web**: pantalla de revisión, en español e inglés, modo claro y oscuro, con tu nombre, color y logo.

## Precisión

Con el modelo por defecto, `gemini-3.8-flash`, lee bien **160–161 de 162 datos** en un conjunto de 27 facturas reales de proveedores revisadas a mano: facturas escritas a mano, tickets de impresora térmica, fotos de papel arrugado, escaneos, abonos y un PDF con tres facturas dentro. Se eligió tras comparar cinco modelos de Gemini con ese conjunto, donde empató en el mayor número de datos bien leídos, con unos 6 s y menos de un céntimo de dólar por factura.

Los demás proveedores se conectan igual, pero no se han medido con ese conjunto. `asienta bench` hace la misma comparación con tus propias facturas ([detalles](docs/ai-models.md)).

## Puesta en marcha

```bash
pip install "git+https://github.com/73bruno/asienta"
asienta --demo            # http://localhost:8760, contabilidad y facturas ficticias, sin clave de API
```

Con tus datos:

```bash
asienta init              # crea config.ini y ledger/ con CSV de ejemplo
export GEMINI_API_KEY=…
asienta check             # prueba el modelo y la conexión con la contabilidad
asienta
```

## Configuración

Cada parte se elige en `config.ini`:

```ini
[reader]
provider = gemini              ; gemini | claude | openai | ollama
model = gemini-3.8-flash

[ledger]
source = csv                   ; csv | sage50

[export]
format = sage50                ; sage50 | contaplus | sage50xls | a3 | holded | xero | quickbooks | csv | json

[inbox]
folder = ~/Dropbox/Facturas    ; opcional, [mailbox] para IMAP

; categorías de línea que asigna el LLM y la cuenta a la que va cada una
[categories]
food   = 600000100 | comida, ingredientes, salsas
drinks = 600000200 | vino, cerveza, refrescos, agua, café
```

Para que las facturas no salgan de tu red, usa un modelo local:

```ini
[reader]
provider = ollama
model = llama3.2-vision
```

La contabilidad mínima es un CSV con el plan de cuentas y los proveedores; con un segundo CSV de a qué cuentas han ido las facturas de cada proveedor, propone cuentas desde el primer día. Formatos en [docs/ledger.md](docs/ledger.md).

## Adaptarlo

Lectores, fuentes de contabilidad y exportadores son clases pequeñas registradas en un diccionario.

**Otro programa de contabilidad.** Un exportador recibe asientos aprobados y cuadrados y escribe un fichero. Hay uno completo de unas 15 líneas en [docs/extending.md](docs/extending.md); al registrarlo en `asienta/exporters/__init__.py`, el test que pasa todos los exportadores por las facturas de la demo lo incluye.

**Otro LLM.** Si tiene endpoint compatible con OpenAI, basta con `provider = openai` y `base_url`. Si no, un lector es una clase con un método `read()` que devuelve el JSON del esquema.

**Otra contabilidad.** Cualquier objeto con un `load()` que devuelva nombres de cuentas, NIF y cuentas habituales por proveedor.

**Otro país.** La validación de NIF y los periodos de IVA están en `asienta/spain.py`; el cambio principal es un módulo equivalente para ese país.

**Integraciones.** Todo lo que hace la interfaz pasa por una API HTTP pequeña: subir, leer el resultado, aprobar, exportar y descargar ([docs/api.md](docs/api.md)).

## Cómo decide

- **Proveedor**: por NIF en tu contabilidad y, si no, por nombre. Si lo eliges a mano, lo recuerda.
- **Cuentas**: a la que más han ido este año las facturas de ese proveedor; las líneas se reparten por categoría, así que el vino de una factura de comida va a bebidas.
- **Fecha contable**: la de la factura, o el primer día abierto si ese trimestre ya tiene el IVA presentado.
- **Comprobaciones**: un NIF que no pasa el dígito de control se corrige en un clic con el de tu contabilidad; totales, IVA, fechas, duplicados, retenciones y posibles inmovilizados se avisan antes de aprobar.

Más en [docs/how-it-works.md](docs/how-it-works.md).

## Estructura

```
asienta/
  extraction/   lectores de LLM (gemini, claude, openai_compat, demo) y el esquema JSON
  ledger/       fuentes de contabilidad (csv, sage50) y el directorio de proveedores y cuentas
  rules.py      proveedor, cuentas, reparto de líneas, fecha contable
  checks.py     todo lo que se avisa antes de aprobar
  exporters/    un módulo por formato de contabilidad
  spain.py      NIF y periodos de IVA españoles
  mailbox.py    entrada por IMAP
  app.py        el flujo; server.py la API HTTP; web/ la interfaz (sin compilar)
tests/          flujo completo con la demo, exportadores, API, lectores (simulados)
scripts/        datos y vídeo de la demo, medición de velocidad
```

Solo biblioteca estándar: `http.server`, `sqlite3`, `urllib` y JavaScript sin frameworks. Paquetes opcionales para Claude, SQL de Sage 50 y Excel. El paquete ocupa 240 KB y usa 26 MB de RAM en reposo; reglas y comprobaciones tardan unos 2 ms por factura (`python scripts/speed.py`).

## Desarrollo

```bash
git clone https://github.com/73bruno/asienta && cd asienta
pip install -e ".[dev]"
pytest                    # unos segundos, sin red
```

Se agradecen contribuciones, sobre todo exportadores para otros programas y experiencias importando los formatos beta en los programas reales. Ver [CONTRIBUTING.md](CONTRIBUTING.md).

## Licencia

[MIT](LICENSE).

<sub>Sage 50, ContaPlus, a3ASESOR, Holded, Xero y QuickBooks son marcas de sus dueños; este proyecto no tiene relación con ellos.</sub>
