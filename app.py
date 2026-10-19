import time
import streamlit as st

from utils.pdf_loader import load_pdf
from utils.chunking import split_text
from utils.vector_store import create_vector_store
from utils.rag_pipeline import create_llm


st.set_page_config(
    page_title="FloatChat",
    page_icon="🤖",
    layout="wide"
)

st.markdown(
    """
    <style>

    /* Main App */
    .stApp {
        background-color: #0E1119;
        color: white;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #161B22 !important;
    }

    /* Chat Messages */
    div[data-testid="stChatMessage"] {
        background-color: #1E2633;
        padding: 12px;
        border-radius: 12px;
        margin-bottom: 10px;
    }

    /* Input Box */
    div[data-baseweb="input"] {
        background-color: #1E2633 !important;
        border-radius: 10px;
    }

    input {
        color: white !important;
    }

    /* Buttons */
    button[kind="secondary"] {
        background-color: #238636 !important;
        color: white !important;
        border-radius: 10px !important;
    }

    button[kind="secondary"]:hover {
        background-color: #2EA043 !important;
    }

    /* Expander */
    .streamlit-expanderHeader {
        background-color: #1E2633;
        border-radius: 10px;
    }

    </style>
    """,
    unsafe_allow_html=True
)


@st.cache_resource
def process_pdf(uploaded_files):

    all_chunks = []

    for uploaded_file in uploaded_files:

        with open(uploaded_file.name, "wb") as f:
            f.write(uploaded_file.read())

        documents = load_pdf(uploaded_file.name)

        for doc in documents:

            chunks = split_text(doc["text"])

            for chunk in chunks:

                all_chunks.append(
                    {
                        "text": chunk,
                        "page": doc["page"],
                        "source": uploaded_file.name
                    }
                )
    vector_store = create_vector_store(all_chunks)

    return vector_store


if "messages" not in st.session_state:
    st.session_state.messages = []


# ---------------- SIDEBAR ----------------

with st.sidebar:

    st.title("⚙️ FloatChat")

    uploaded_files = st.file_uploader(
        "Upload PDF",
        type="pdf",
        accept_multiple_files=True
    )

    if uploaded_files:                                                                            #check this

        st.success("PDF Uploaded Successfully")

        st.write(f"{len(uploaded_files)} PDFs Uploaded")

        for file in uploaded_files:
            st.write(file.name)

    if st.button("🗑️ Clear Chat"):

        st.session_state.messages = []

        st.rerun()

    st.markdown("---")

    st.markdown(
        """
        ### About
        FloatChat is a RAG-based AI Assistant.
        Built with:
        - Streamlit
        - LangChain
        - FAISS
        - Groq
        """
    )


# ---------------- MAIN CHAT ----------------

st.title("🤖 FloatChat AI Assistant")

st.caption(
    "Upload PDFs and chat with your documents using AI 🚀"
)

st.divider()

st.write("Chat with your PDF using AI")


if uploaded_files:

    with st.spinner("Processing PDF..."):

        vector_store, bm25_retriever = process_pdf(uploaded_files)

    # Display old messages
    for message in st.session_state.messages:

        with st.chat_message(message["role"]):

            st.markdown(message["content"])

    # Chat input
    query = st.chat_input("Ask a question about your PDF")

    if query:
        original_query = query

        search_query = query.lower().strip()

    if query:

        # Store user message
        st.session_state.messages.append(
            {
                "role": "user",
                "content": query
            }
        )

        # Show user message
        with st.chat_message("user"):

            st.markdown(query)

        # Generate AI response
        with st.chat_message("assistant"):

            with st.spinner("🧠 Analyzing documents and generating answer..."):

                search_query = query

                if len(st.session_state.messages) >= 2:

                    last_user_message = st.session_state.messages[-2]["content"]

                    search_query = f"{last_user_message} {query}"

                faiss_results = vector_store.similarity_search(
                    search_query,
                    k=3
                )

                bm25_results = bm25_retriever.invoke(
                    search_query
                )

                # Combine Results
                results = faiss_results + bm25_results

                # Remove Duplicate Chunks
                unique_results = []

                seen = set()

                for doc in results:

                    if doc.page_content not in seen:

                        unique_results.append(doc)

                        seen.add(doc.page_content)

                results = unique_results[:5]

                if not results:

                    st.warning(
                        "No relevant information found in uploaded documents."
                    )

                    st.stop()

                context = "\n\n".join(
                    [doc.page_content for doc in results]
                )

                chat_history = ""

                recent_messages = st.session_state.messages[-4:]

                for msg in recent_messages:

                    role = msg["role"]
                    content = msg["content"]

                    chat_history += f"{role}: {content}\n"

                llm = create_llm()

                prompt = f"""
                You are FloatChat, an AI assistant that answers questions
                ONLY from the provided PDF context.

                Instructions:
                - Answer only using the provided context
                - Use conversation history for understanding follow-up questions
                - If the answer is not in the context, say:
                "I could not find that information in the uploaded documents."
                - Keep answers clear, professional, and well-structured
                - Use bullet points when appropriate
                - Do not make up information

                Conversation History:
                {chat_history}

                Context:
                {context}

                Current Question:
                {query}

                Answer:
                """

                response = llm.stream(prompt)

                full_response = ""

                response_placeholder = st.empty()

                for chunk in response:

                    full_response += chunk.content

                    response_placeholder.markdown(full_response + "▌")

                    time.sleep(0.02)

                response_placeholder.markdown(full_response)

                ai_answer = full_response

                with st.expander("📚 View Sources"):

                     for i, doc in enumerate(results):

                         st.markdown(f"### Source {i+1}")

                         st.markdown(
                            f"""
                            **Source:** {doc.metadata['source']}<br>
                            **Page:** {doc.metadata['page']}
                            """
                        )

                         st.write(doc.page_content[:500] + "...")

        # Store AI response
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": ai_answer
            }
        )

else:

    st.info(
    "👈 Upload one or more PDFs from the sidebar to start chatting."
)