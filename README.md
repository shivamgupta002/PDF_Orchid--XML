# PDF + ORCID JSON to XML

This Streamlit app takes **two inputs**:
- a complete, selectable-text research article PDF
- the matching ORCID extraction JSON

It reads every PDF page, extracts first-page bibliographic metadata, reads the bibliography using PDF text-block layout (including the two-column references layout in the supplied sample), maps ORCID IDs to printed author surnames, and generates an XML document following the supplied Elsevier-style CAR XML structure.

## Run on Windows PowerShell
```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

No Ollama server, model download, or internet connection is needed.

## Settings
The sidebar exposes supplier ID, TPA-ID, IPUI, source ID, and batch timestamp. These values belong to the XML batch envelope and should be confirmed for each production batch.

## Validation performed with the supplied sample
- Read all 6 PDF pages.
- Extracted the title, DOI, journal, year, volume, issue, page range, abstract, and 5 keywords.
- Detected 3 authors and mapped all 3 ORCID IDs from the JSON.
- Extracted 20 numbered bibliography entries.
- Parsed the generated XML successfully with Python's XML parser.

## Important production notes
- This version is tuned to the first-page and reference layout in the supplied *Asian Journal of Chemistry* sample. Different publisher layouts may need additional parsing rules.
- Image-only/scanned PDFs require OCR before upload.
- The output follows the structure and namespaces of the provided XML example, but it has **not** been validated against your organization's CAR XSD or production ingestion service. Validate the XML with the official XSD and review it before production use.
- Some fields present in the example XML (for example internal IPUI, source ID, batch envelope values) are not contained in the PDF/ORCID JSON. Enter the correct values in the sidebar rather than assuming the defaults are valid for another article.
- The program deliberately does not infer publisher name, received/accepted dates, or fields not reliably extracted from the two input files.
