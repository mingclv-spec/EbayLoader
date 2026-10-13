# AI-assisted book-to-eBay listing workflow

This is an additive web workflow for the existing EbayLoader Python project. It does not replace the current CLI, API/authentication code, batch CSV loader, or Git history.

## Start the web app (Windows PowerShell)

From C:\project\EbayLoader:

    py -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    streamlit run ebayloader/webapp.py

Streamlit opens the app in your browser. Upload a cover, ISBN/barcode/back-cover, copyright page, and photos of defects. Enter the ISBN or optionally try OCR, run research, review and correct fields, then export CSV or Excel.

## Optional OCR

The app works without OCR; enter the ISBN manually. For OCR support, install requirements-ocr.txt. Install the Tesseract OCR engine separately and ensure tesseract.exe is on PATH. OCR is fallible, so verify the ISBN before lookup.

## Research and evidence

- Open Library ISBN endpoint and Google Books API are queried automatically.
- Publisher-site discovery and general web research are offered as search links; a best-effort DuckDuckGo HTML search is also attempted.
- eBay active and sold/completed search links are generated for manual comparison. This app does not claim to download verified eBay sold prices; generally accessible eBay APIs do not provide a universal unauthenticated sold-history dataset for this workflow.
- Research source URLs are exported with the draft. Keep unconfirmed facts blank.

## Safety and scope

- Listing preparation only; the app does not publish or change eBay listings.
- Existing CLI modules, eBay API/authentication code, batch CSV loader, config, and CLI entry point remain unchanged.
- The app keeps the draft in the current Streamlit session. Download exports to preserve it.
- The current export schema is in ebayloader/webapp.py. Customize it as your seller requirements become clear.

## Suggested next steps

1. Test ISBN matching across books with different editions.
2. Refine required fields, category/aspects and condition mapping for your seller account.
3. If desired, add authenticated eBay listing creation only after draft review and explicit publish confirmation.


## Optional AI-assisted description

Set the OPENAI_API_KEY environment variable before starting Streamlit to enable description drafting. OPENAI_MODEL is optional and defaults to gpt-4.1-mini. The feature sends only the selected bibliographic and condition fields to the OpenAI API. Do not put the API key in source control. Generated text is a draft and must be reviewed.
