import streamlit as st
from pdf_to_xml import build_xml, inspect_pdf

st.set_page_config(page_title="PDF + ORCID JSON to XML", page_icon="📄", layout="wide")
st.title("PDF + ORCID JSON → XML")
st.write("Upload a complete research-article PDF and its ORCID extraction JSON. The app reads the PDF text, combines author ORCID identifiers, and creates XML in the supplied Elsevier-style CAR structure.")

with st.sidebar:
    st.header("XML output settings")
    supplier_id = st.text_input("Supplier ID", "116260")
    tpa_id = st.text_input("TPA-ID", "")
    ipui = st.text_input("IPUI (optional)", "")
    source_id = st.text_input("Source ID (optional)", "77794899")
    batch_timestamp = st.text_input("Batch timestamp", "2026-11-21T00:00:00")
    st.caption("These are output-envelope values. Article metadata is extracted from the PDF and ORCID JSON.")

pdf_file = st.file_uploader("1. Upload research article PDF", type=["pdf"])
json_file = st.file_uploader("2. Upload matching ORCID JSON", type=["json"])

if pdf_file and json_file:
    try:
        preview = inspect_pdf(pdf_file.getvalue())
        st.subheader("PDF inspection")
        c1, c2, c3 = st.columns(3)
        c1.metric("Pages read", preview["page_count"])
        c2.metric("References detected", preview["reference_count"])
        c3.metric("Authors detected", len(preview["authors"]))
        st.write("**Article title:**", preview["article_title"])
        st.write("**DOI:**", preview["doi"])
        st.write("**Journal:**", preview["journal_name"])
        st.write("**Authors:**", ", ".join(a["name"] for a in preview["authors"]))
        if preview["reference_count"] == 0:
            st.warning("No reference entries were detected. Check that the PDF contains a selectable-text REFERENCES section.")
        if st.button("Generate XML", type="primary"):
            xml_bytes, report = build_xml(
                pdf_file.getvalue(), json_file.getvalue(),
                supplier_id=supplier_id, tpa_id=tpa_id, ipui=ipui,
                batch_timestamp=batch_timestamp, source_id=source_id
            )
            st.success("XML generated.")
            st.subheader("Extraction report")
            st.json(report)
            st.download_button(
                "Download generated XML",
                data=xml_bytes,
                file_name=(pdf_file.name.rsplit(".", 1)[0] + ".xml"),
                mime="application/xml"
            )
            with st.expander("Preview generated XML"):
                st.code(xml_bytes.decode("utf-8"), language="xml")
    except Exception as exc:
        st.error(f"Processing failed: {exc}")
else:
    st.info("Upload both files to inspect the PDF and enable XML generation.")

st.caption("The app does not use Ollama or an external LLM. It uses PDF text/layout extraction and deterministic XML generation so that bibliographic fields are not invented. Review the generated XML before production use.")
