from __future__ import annotations
import json
import re
import xml.etree.ElementTree as ET
from typing import Any
import fitz

NS = "http://www.elsevier.com/xml/ani/ani"
CE = "http://www.elsevier.com/xml/ani/common"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
ET.register_namespace("", NS)
ET.register_namespace("ce", CE)
ET.register_namespace("xsi", XSI)

def q(tag: str, ns: str = CE) -> str:
    return f"{{{ns}}}{tag}"

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def read_pdf(pdf_bytes: bytes) -> tuple[list[str], str]:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        pages = [p.get_text("text", sort=True) for p in pdf]
    return pages, "\n".join(pages)

def extract_references(pages: list[str], pdf_bytes: bytes | None = None) -> list[str]:
    # Use PDF text blocks so two-column bibliographies are read column-by-column.
    # This avoids the common error where sorted page text interleaves both columns.
    chunks: list[str] = []
    if pdf_bytes:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
            for page in pdf:
                blocks = page.get_text("blocks")
                heading = None
                for b in blocks:
                    if re.search(r"\bREFERENCES\b", b[4], re.I):
                        heading = b
                        break
                if heading:
                    mid = page.rect.width / 2
                    left = [b for b in blocks if b[0] < mid and b[1] >= heading[1] and b[4].strip()]
                    right = [b for b in blocks if b[0] >= mid and b[1] > 45 and b[4].strip()]
                    # A reference heading normally starts the left column. The right
                    # column may continue from its top, so include numbered blocks there.
                    for group in (sorted(left, key=lambda z: z[1]), sorted(right, key=lambda z: z[1])):
                        chunks.extend(b[4] for b in group if re.search(r"(?m)^\s*\d{1,2}\.\s*", b[4]))
                    if chunks:
                        break
    if not chunks:
        full = "\n".join(pages)
        m = re.search(r"REFERENCES", full, re.I)
        if not m:
            return []
        chunks = [full[m.end():]]
    bibliography_text = "\n".join(chunks)
    # Each citation begins with a numbered marker. A marker may be on a separate
    # line from the author names, as happens in the uploaded journal PDF.
    starts = list(re.finditer(r"(?m)^\s*(\d{1,2})\.\s*", bibliography_text))
    refs: dict[int, str] = {}
    for i, match in enumerate(starts):
        number = int(match.group(1))
        end = starts[i+1].start() if i+1 < len(starts) else len(bibliography_text)
        body = bibliography_text[match.end():end]
        body = re.sub(r"(?m)^\s*\d{1,2}\.\s*$", "", body)
        body = clean(body.replace("\n", " "))
        body = re.sub(r"\s+", " ", body)
        if 1 <= number <= 99 and body:
            refs[number] = body
    return [refs[n] for n in sorted(refs)]

def parse_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    pages, full = read_pdf(pdf_bytes)
    if not pages or not clean(full):
        raise ValueError("The PDF contains no selectable text. OCR is required for scanned PDFs.")
    p1 = pages[0]
    lines = [clean(x) for x in p1.splitlines() if clean(x)]
    journal = ""
    m = re.search(r"(?m)^\s*(.+?)\s*;\s*Vol\.?\s*(\d+)\s*,?\s*No\.?\s*(\d+)\s*\((\d{4})\)\s*,?\s*(\d+)\s*[-–—]\s*(\d+)", p1)
    volume = issue = year = first_page = last_page = ""
    if m:
        journal, volume, issue, year, first_page, last_page = [x.strip() for x in m.groups()]
    doi_m = re.search(r"(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", full, re.I)
    doi = doi_m.group(1).rstrip(".,;:)]}") if doi_m else ""
    # Detect the author byline from uppercase names followed by affiliation markers.
    author_line_idx = next(
        (i for i, line in enumerate(lines)
         if re.search(r"\b[A-Z][A-Z'’-]+(?:\s+[A-Z][A-Z'’-]+)+\s*\d", line)),
        None
    )
    author_line = lines[author_line_idx] if author_line_idx is not None else ""
    title = ""
    if author_line_idx is not None:
        title = clean(" ".join(lines[max(0, author_line_idx-2):author_line_idx]))
        title = re.sub(r"\s*[\d*]+$", "", title).strip()

    # The first-page abstract is unheaded in this journal; it starts after publication data.
    abstract = ""
    pub_idx = next((i for i,x in enumerate(lines) if "Published online:" in x), None)
    if pub_idx is not None:
        chunks=[]
        for x in lines[pub_idx+1:]:
            if re.match(r"^Keywords\s*:", x, re.I):
                break
            if re.match(r"^(?:INTRODUCTION|EXPERIMENTAL)\b", x, re.I):
                break
            chunks.append(x)
        abstract = clean(re.sub(r"-\s+", "", " ".join(chunks)))
    kw_m = re.search(r"(?im)^\s*Keywords?\s*:\s*(.+)$", p1)
    keywords = [clean(x).rstrip(".,;") for x in kw_m.group(1).split(",")] if kw_m else []

    # Parse author names and superscript affiliation numbers from the printed byline.
    names = []
    if author_line:
        pattern = r"([A-Z][A-Z'’-]+(?:\s+[A-Z][A-Z'’-]+)+)\s*((?:\d+(?:,\d+)*))"
        for match in re.finditer(pattern, author_line):
            full_name = clean(match.group(1)).title()
            parts = full_name.split()
            if len(parts) >= 2:
                given, surname = " ".join(parts[:-1]), parts[-1]
                aff_numbers = re.findall(r"\d+", match.group(2))
                names.append({"given":given, "surname":surname,
                              "name":full_name, "affs":aff_numbers})
    affs = {}
    for line in lines:
        am = re.match(r"^(\d{1,2})\s*(.+(?:India|USA|United Kingdom))$", line)
        if am:
            affs[am.group(1)] = clean(am.group(2))
    email_match = re.search(r"Corresponding author:\s*E-mail:\s*([^\s]+)", p1, re.I)
    corr_email = email_match.group(1).rstrip(".,;") if email_match else ""
    refs = extract_references(pages, pdf_bytes)
    # Some PDFs use two-column layout and text extraction can interleave columns.
    # Preserve the detected numbered records; report count for human QA.
    return {"pages": pages, "journal": journal, "volume": volume, "issue": issue,
            "year": year, "first_page": first_page, "last_page": last_page,
            "doi": doi, "title": title, "abstract": abstract, "keywords": keywords,
            "authors": names, "affiliations": affs, "corr_email": corr_email, "references": refs}

def load_orcid(data: bytes) -> list[dict[str, Any]]:
    raw = json.loads(data.decode("utf-8-sig"))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        # The uploaded crawler JSON is keyed by PDF filename.
        for value in raw.values():
            if isinstance(value, list):
                return value
    raise ValueError("ORCID JSON must be a list, or an object containing a list of author records.")

def orcid_for_author(author: dict[str, Any], records: list[dict[str, Any]]) -> str:
    target = author["surname"].casefold()
    for rec in records:
        source = clean(rec.get("source_text", ""))
        # Hyperlink context commonly looks like "SINGH1,2,*, PARUL".
        source_surname = re.match(r"^([A-Za-zÀ-ÖØ-öø-ÿ'’-]+)", source)
        if source_surname and source_surname.group(1).casefold() == target:
            return re.sub(r"^https?://orcid\.org/", "", rec.get("orcid", "").strip())
    # Fallback requires both given name and surname to match.
    for rec in records:
        if (clean(rec.get("surname", "")).casefold() == target and
                clean(rec.get("givenname", "")).casefold() == clean(author["given"]).casefold()):
            return re.sub(r"^https?://orcid\.org/", "", rec.get("orcid", "").strip())
    return ""

def add(parent, tag, text=None, attrs=None, ns=NS):
    el = ET.SubElement(parent, q(tag, ns), attrs or {})
    if text is not None:
        el.text = str(text)
    return el

def build_xml(pdf_bytes: bytes, json_bytes: bytes, supplier_id="116260",
              tpa_id="", ipui="", batch_timestamp="", source_id="77794899") -> tuple[bytes, dict[str, Any]]:
    data = parse_pdf(pdf_bytes)
    orcid_records = load_orcid(json_bytes)
    if not data["title"]:
        raise ValueError("Could not detect the article title/byline on page 1. Check PDF text extraction.")
    root = ET.Element(q("units", NS), {
        f"{{{XSI}}}schemaLocation": f"{NS} http://www.elsevier.com/xml/ani/ani515-input-CAR.xsd"
    })
    unit = add(root, "unit", ns=NS, attrs={"type":"BATCH"})
    info = add(unit, "unit-info", ns=NS)
    add(info, "unit-id", "1", ns=NS)
    add(info, "order-id", "none", ns=NS)
    add(info, "parcel-id", "none", ns=NS)
    add(info, "supplier-id", supplier_id, ns=NS)
    add(info, "timestamp", batch_timestamp or "none", ns=NS)
    content = add(unit, "unit-content", ns=NS)
    bib = add(content, "bibrecord", ns=NS)
    iteminfo = add(bib, "item-info", ns=NS)
    status = add(iteminfo, "status", ns=NS, attrs={"state":"new","stage":"S300"})
    ids = add(iteminfo, "itemidlist", ns=NS)
    if data["doi"]: add(ids, "doi", data["doi"], ns=CE)
    if ipui: add(ids, "itemid", ipui, {"idtype":"IPUI"})
    if tpa_id: add(ids, "itemid", tpa_id, {"idtype":"TPA-ID"})
    head = add(bib, "head", ns=NS)
    ci = add(head, "citation-info", ns=NS)
    add(ci, "citation-type", attrs={"code":"ar"})
    add(ci, "citation-language", attrs={"{http://www.w3.org/XML/1998/namespace}lang":"ENG"})
    add(ci, "abstract-language", attrs={"{http://www.w3.org/XML/1998/namespace}lang":"ENG"})
    kw = add(ci, "author-keywords")
    for word in data["keywords"]:
        add(kw, "author-keyword", word, {"{http://www.w3.org/XML/1998/namespace}lang":"ENG","original":"y"})
    title_el = add(head, "citation-title")
    add(title_el, "titletext", data["title"], {"{http://www.w3.org/XML/1998/namespace}lang":"ENG","original":"y"})
    # Build one author-group per numbered affiliation, preserving the source PDF's
    # author-affiliation relationships (an author can appear in multiple groups).
    for affno in sorted(data["affiliations"], key=lambda x: int(x)):
        associated = [a for a in data["authors"] if affno in a["affs"]]
        if not associated:
            continue
        group = add(head, "author-group", attrs={"seq":affno})
        for author in associated:
            idx = data["authors"].index(author) + 1
            attrs = {"seq":str(idx)}
            oid = orcid_for_author(author, orcid_records)
            if oid:
                attrs["orcid"] = oid
            ae = add(group, "author", attrs=attrs)
            add(ae, "initials", author["given"][0] + ".", ns=CE)
            add(ae, "surname", author["surname"], ns=CE)
            add(ae, "given-name", author["given"], ns=CE)
            if author["surname"] == data["authors"][0]["surname"] and data["corr_email"]:
                add(ae, "e-address", data["corr_email"], ns=CE)
        aff = add(group, "affiliation")
        aff_text = data["affiliations"].get(affno, "")
        # Parse common "organization(s), City-PostalCode, Country" format.
        city_match = re.search(r",\s*([^,]+?)[- ](\d{5,6}),\s*(India|USA|United Kingdom)$", aff_text, re.I)
        if city_match:
            org_text = aff_text[:city_match.start()].strip(" ,")
            for organization in [x.strip() for x in org_text.split(",") if x.strip()]:
                add(aff, "organization", organization)
            add(aff, "city", city_match.group(1).strip())
            add(aff, "postal-code", city_match.group(2))
            country = city_match.group(3).casefold()
            add(aff, "country", attrs={"iso-code":"IND"} if country == "india" else {"iso-code":"USA"})
        else:
            add(aff, "organization", aff_text)
        add(aff, "source-text", aff_text, ns=CE)
    corr = add(head, "correspondence")
    person = add(corr, "person")
    add(person, "initials", "P.", ns=CE)
    if data["authors"]:
        add(person, "surname", data["authors"][0]["surname"], ns=CE)
        add(person, "given-name", data["authors"][0]["given"], ns=CE)
    if data["corr_email"]:
        add(corr, "e-address", data["corr_email"], ns=CE)
    abstracts = add(head, "abstracts")
    abstract = add(abstracts, "abstract", attrs={"{http://www.w3.org/XML/1998/namespace}lang":"ENG","original":"y"})
    add(abstract, "para", data["abstract"], ns=CE)
    source = add(head, "source", attrs={"srcid":source_id} if source_id else {})
    voliss = add(source, "volisspag")
    vin = add(voliss, "volume-issue-number")
    if data["volume"]: add(vin, "vol-first", data["volume"])
    if data["issue"]: add(vin, "iss-first", data["issue"])
    pi = add(voliss, "page-information")
    pages = add(pi, "pages")
    if data["first_page"]: add(pages, "first-page", data["first_page"])
    if data["last_page"]: add(pages, "last-page", data["last_page"])
    if data["year"]: add(source, "publicationyear", attrs={"first":data["year"]})
    tail = add(bib, "tail", ns=NS)
    bibel = add(tail, "bibliography", attrs={"refcount":str(len(data["references"]))})
    for i, ref in enumerate(data["references"], 1):
        relem = add(bibel, "reference", attrs={"seq":str(i)})
        add(relem, "ref-info")
        add(relem, "ref-fulltext", f"{i}. {ref}")
        add(relem, "source-text", f"{i}. {ref}", ns=CE)
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    # Pretty-print without changing namespace semantics.
    parsed = ET.fromstring(xml_bytes)
    ET.indent(parsed, space="  ")
    xml_bytes = ET.tostring(parsed, encoding="utf-8", xml_declaration=True)
    report = {"article_title":data["title"], "doi":data["doi"], "journal":data["journal"],
              "year":data["year"], "volume":data["volume"], "issue":data["issue"],
              "pages":f'{data["first_page"]}-{data["last_page"]}',
              "authors":[{"name":a["name"],"orcid":orcid_for_author(a,orcid_records)} for a in data["authors"]],
              "keywords":data["keywords"], "references_detected":len(data["references"]),
              "pdf_pages_read":len(data["pages"])}
    return xml_bytes, report

def inspect_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    d = parse_pdf(pdf_bytes)
    return {"page_count":len(d["pages"]), "reference_count":len(d["references"]),
            "authors":d["authors"], "article_title":d["title"], "doi":d["doi"],
            "journal_name":d["journal"]}
