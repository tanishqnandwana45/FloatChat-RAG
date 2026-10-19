from pypdf import PdfReader


def load_pdf(file_path):
    reader = PdfReader(file_path)

    documents = []

    for page_num, page in enumerate(reader.pages):

        text = page.extract_text()

        if text:
            documents.append(
                {
                    "text": text,
                    "page": page_num + 1
                }
            )

    return documents