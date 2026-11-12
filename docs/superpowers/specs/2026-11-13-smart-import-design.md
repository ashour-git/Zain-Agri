# Smart import of products and opening stock - Design

Status: written 2026-11-13, awaiting owner review
Owner: ZAIN AGRI web + API

## 1. Purpose

Zain's shop runs on an Excel workbook, and the owner does not have a sample
file to share. The importer must therefore work with any layout instead of one
fixed template: the owner uploads a sheet, the site's assistant proposes which
column is which, the owner checks a preview, and one confirmation creates the
products with their starting quantities. A blank template is offered for
people who have no sheet at all.

### Decisions taken with the owner

| Topic | Decision |
|---|---|
| Layout | Any layout; the assistant proposes a column mapping, the owner confirms |
| Starting point | No real sample file exists, so tests use generated sheets in several layouts |
| Order | Built after stocktake (done) |

### Out of scope (this version)

- Updating or overwriting products that already exist (they are skipped).
- Importing from photos of a paper notebook (not verified to work on the free tier).
- Importing customers, suppliers, sales or prices history.
- Legacy `.xls` files (the owner saves as `.xlsx` first; the screen says so).
- Editing individual cells in the preview (fix the sheet or the mapping, then re-run).

## 2. Flow

1. **Upload** `.xlsx` or `.csv`, up to 4 MB and 2,000 data rows.
2. **Columns.** The server reads the sheet, finds the header row, and returns the
   columns with three sample values each. The assistant proposes a field for each
   column; the owner can change any of them. A badge says whether the proposal
   came from the assistant or from built-in header rules.
3. **Preview.** The server normalizes every row and reports: will create, will
   skip (already exists or duplicate in the file), has a problem (with the row
   number and an Arabic reason). Nothing is saved yet.
4. **Confirm.** One transaction creates categories and brands that are new,
   the products, and an opening-balance movement for each row with a quantity.
   All or nothing. The result screen states the counts.

The flow is stateless on the server: the browser keeps the parsed rows between
steps and sends them back with the mapping. The server re-validates everything
on preview and again on confirm, and never trusts the preview.

## 3. Fields

| Field | Required | Notes |
|---|---|---|
| `name_ar` | yes | product name |
| `sku` | no | generated as `Z-00001`, `Z-00002`... per shop when missing |
| `barcode` | no | |
| `unit` | no | text such as كيلو, شيكارة, لتر mapped to the unit list; default unit chosen on screen (قطعة) and the row is flagged when the text is unknown |
| `category`, `brand` | no | matched by normalized name; new ones are created if the owner leaves "create new" on |
| `sale_price` | no | |
| `cost_price` | no | only applied when the user has the cost permission, otherwise ignored with a notice |
| `minimum_stock` | no | |
| `quantity` | no | becomes the opening balance |
| `ignore` | | default for every column that matches nothing |

### Normalization

Arabic-Indic digits to Western, thousand separators and the Arabic decimal mark,
currency text («ج.م», «جنيه») stripped from prices, spaces collapsed, unit and
category names compared after removing diacritics and unifying أ/إ/ا, ى/ي,
ة/ه. Title rows above the header and a totals row (الإجمالي, المجموع, total, or a
row with numbers and no name) are detected and skipped, and counted in the preview.
Formulas are never evaluated: the sheet is read for its saved values only.

## 4. The assistant's part

- One request per upload, through the existing Groq client and model fallback.
- **What is sent:** each column's header text and up to three sample values, with
  values that look like phone numbers or emails replaced by a placeholder. Never
  the whole sheet. The screen says so before the owner continues, and offers
  "map the columns myself" which skips the assistant entirely.
- **What is accepted back:** a JSON list of `{column, field}` where `field` must be
  one of the fields in §3. Anything else is dropped. Text inside headers or cells
  is data, never instructions (the same rule as the shop assistant).
- **Built-in rules first:** a table of Arabic and English header synonyms
  (اسم الصنف, البيان, المنتج, السعر, سعر البيع, الكمية, الرصيد, الوحدة, barcode...)
  fills the mapping before and after the assistant, so a sheet still maps when
  the assistant is busy or off. The result says which source mapped each column.
- Counts as one use of the shop's daily assistant limit.
- **Not yet measured:** how accurately the free models map real sheets. Before the
  feature is called done, an evaluation over at least ten generated layouts reports
  a figure, in the same style as `tests/evals`.

## 5. Writes

- A non-committing core `create_product_core` is split out of `create_product`
  (like `apply_movement`), so the import creates all products in one transaction.
  `create_product` keeps its behaviour and tests.
- Opening balances use `apply_movement`. A product that tracks batches is not
  created by import (batch products are added on the products screen).
- Needs both `products.create` and `inventory.adjust`.
- Skipped when the product exists: same `sku`, same `barcode`, or same normalized
  name and unit. Importing the same sheet twice creates nothing the second time.
- One audit entry `import.committed` with counts; each product and movement is also
  audited by the existing paths. Limit 2,000 rows per import.

## 6. API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/imports/analyze` | multipart file; returns sheets, header row, columns with samples, proposed mapping, source |
| POST | `/api/v1/imports/preview` | `{mapping, rows, options}`; returns per-row status and counts |
| POST | `/api/v1/imports/commit` | same body; creates everything, atomically |
| GET | `/api/v1/imports/template` | blank `.xlsx` with Arabic headers and one example row |

All require `products.create` and `inventory.adjust`. Errors use the existing
envelope with Arabic messages.

## 7. Screens

`/products/import`, opened from a button on the products screen. Four steps in
one page: file, columns (a dropdown per column, pre-filled), preview (counts first,
then the problem rows, then a sample of good rows), result. Western digits, ledger
look, RTL, usable at phone width, loading and error states, and a link to the template.

## 8. Testing

- Generated files in several layouts: Arabic headers, English headers, title rows
  and a totals row, prices with currency text, Arabic digits, quantity column named
  «الجرد» or «الرصيد», CSV in UTF-8 and Windows-1256.
- Parser: header-row detection, merged cells, empty rows, formulas not evaluated,
  oversize file and row limits, a non-spreadsheet file refused with an Arabic message.
- Mapping: hostile assistant output (unknown fields, instructions in a header)
  is ignored; with the assistant unavailable the rules still map common headers.
- Commit: atomic (one bad row creates nothing), second run creates nothing,
  generated SKUs do not collide, cost ignored without the permission,
  categories and brands matched and created once.
- Permissions: cashier refused; owner and storekeeper behave per §5.
- Isolation: shop A's products never affect shop B's import.
- Balance equals the sum of movements after an import.
- Evaluation of mapping accuracy over at least ten layouts (reported, not asserted).

## 9. Risks

- Free-tier models can map a column wrongly. The owner sees and edits every
  mapping before anything is saved, and the preview shows the effect.
- A sheet with customer data in other columns still sends three sample values of
  those columns to the model. Mitigations: redaction of phone-like and email-like
  values, a notice on screen, and the option to skip the assistant.
- Quantities in the sheet may be a different unit from the price. The unit column
  decides; rows with unknown units are flagged, not guessed.
