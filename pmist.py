"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              PERIYAR — PMIST AI Representative                              ║
║              Single-file: Scrape → Clean → Index → Chat                    ║
╚══════════════════════════════════════════════════════════════════════════════╝

HOW TO RUN:
    pip install selenium webdriver-manager langchain langchain-community
        langchain-huggingface langchain-groq faiss-cpu sentence-transformers
        python-dotenv

    Then create a .env file in the same folder:
        GROQ_API_KEY=your_groq_key_here

    Run:
        python periyar_pmist.py                 # full run (scrape + index + chat)
        python periyar_pmist.py --chat-only     # skip scraping, use existing index
        python periyar_pmist.py --scrape-only   # only scrape + index, no chat
"""

# ─────────────────────────────────────────────────────────────
#  IMPORTS
# ─────────────────────────────────────────────────────────────
import os, sys, time, re, argparse
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# ─────────────────────────────────────────────────────────────
#  CONFIG  —  change only these values if needed
# ─────────────────────────────────────────────────────────────
BASE_URL          = "https://pmu.edu"
STUDENT_PORTAL    = "https://pmiststudentportal.in"
RAW_FILE          = "pmist_raw.txt"
CLEAN_FILE        = "pmist_clean.txt"
FAISS_DIR         = "pmist_faiss_index"
EMBED_MODEL       = "sentence-transformers/all-MiniLM-L6-v2"
LLM_MODEL         = "llama-3.3-70b-versatile"
CHUNK_SIZE        = 600
CHUNK_OVERLAP     = 80
TOP_K             = 6
PAGE_LOAD_WAIT    = 4
HOVER_WAIT        = 1.5


# ══════════════════════════════════════════════════════════════
#  STEP 1 — SCRAPE
# ══════════════════════════════════════════════════════════════
def scrape_website():
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.common.action_chains import ActionChains
    from webdriver_manager.chrome import ChromeDriverManager

    print("\n🌐  Starting PMIST website scrape …\n")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    driver  = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    wait    = WebDriverWait(driver, 10)
    actions = ActionChains(driver)

    def normalize(url: str) -> str:
        return url.rstrip("/").split("?")[0].split("#")[0]

    def is_internal(url: str) -> bool:
        return (
            BASE_URL in url or
            STUDENT_PORTAL in url
        )

    def hover_nav_and_collect_links():
        hrefs = set()
        try:
            nav_items = driver.find_elements(
                By.CSS_SELECTOR,
                "nav a, nav button, header a, header button, [class*='nav'] a"
            )
            for item in nav_items:
                try:
                    actions.move_to_element(item).perform()
                    time.sleep(HOVER_WAIT)
                except Exception:
                    pass
        except Exception:
            pass

        for a in driver.find_elements(By.TAG_NAME, "a"):
            href = a.get_attribute("href")
            if href and is_internal(href):
                hrefs.add(normalize(href))
        return hrefs

    def extract_page_content(url: str) -> str:
        lines = [f"PAGE URL: {url}"]

        try:
            lines.append(f"PAGE TITLE: {driver.title}")
        except Exception:
            pass

        try:
            meta = driver.find_element(By.CSS_SELECTOR, 'meta[name="description"]')
            desc = meta.get_attribute("content")
            if desc:
                lines.append(f"META DESCRIPTION: {desc}")
        except Exception:
            pass

        for tag in ["h1", "h2", "h3", "h4"]:
            for el in driver.find_elements(By.TAG_NAME, tag):
                t = el.text.strip()
                if t:
                    lines.append(f"{tag.upper()}: {t}")

        for el in driver.find_elements(
            By.CSS_SELECTOR,
            "nav a, nav li, nav button, [class*='dropdown'] a, "
            "[class*='menu'] a, header nav a"
        ):
            t = el.text.strip()
            if t and len(t) < 120:
                lines.append(f"NAV: {t}")

        for el in driver.find_elements(By.TAG_NAME, "button"):
            t = el.text.strip()
            if t:
                lines.append(f"BUTTON: {t}")

        for el in driver.find_elements(By.TAG_NAME, "a"):
            t    = el.text.strip()
            href = el.get_attribute("href") or ""
            if t and 3 < len(t) < 200:
                lines.append(f"LINK: {t} → {href}")

        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            lines.append("\nFULL PAGE TEXT:\n" + body_text)
        except Exception:
            pass

        return "\n".join(lines)

    visited: set   = set()
    to_visit: list = [normalize(BASE_URL)]

    with open(RAW_FILE, "w", encoding="utf-8") as f:
        while to_visit:
            url = normalize(to_visit.pop())
            if url in visited:
                continue
            visited.add(url)
            print(f"  → Visiting: {url}")

            try:
                driver.get(url)
                time.sleep(PAGE_LOAD_WAIT)

                new_links = hover_nav_and_collect_links()
                for link in new_links:
                    if link not in visited and link not in to_visit:
                        to_visit.append(link)

                for a in driver.find_elements(By.TAG_NAME, "a"):
                    href = a.get_attribute("href")
                    if href and is_internal(href):
                        n = normalize(href)
                        if n not in visited and n not in to_visit:
                            to_visit.append(n)

                content = extract_page_content(url)
                f.write("\n\n" + "=" * 80 + "\n")
                f.write(content)
                f.write("\n" + "=" * 80 + "\n")

            except Exception as e:
                print(f"  ⚠  Error on {url}: {e}")
                continue

    driver.quit()
    print(f"\n✅  Scraping complete! {len(visited)} pages → '{RAW_FILE}'\n")


# ══════════════════════════════════════════════════════════════
#  STEP 2 — CLEAN
# ══════════════════════════════════════════════════════════════
def clean_data():
    print("🧹  Cleaning scraped data …")

    with open(RAW_FILE, "r", encoding="utf-8") as f:
        text = f.read()

    SKIP_PATTERNS = [
        r"^.{0,29}$",
        r"accept.{0,20}cookie",
        r"cookie.{0,20}policy",
        r"privacy policy",
        r"terms of service",
        r"all rights reserved",
        r"©\s*\d{4}",
        r"follow us on",
        r"subscribe to our newsletter",
        r"^\s*[|/\\•·–—]\s*$",
        r"^\s*\d+\s*$",
    ]

    # ✅ Fix: compile each pattern separately with IGNORECASE flag
    skip_res = [re.compile(p, re.IGNORECASE) for p in SKIP_PATTERNS]

    seen   = set()
    result = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Check against each pattern individually
        if any(p.search(line) for p in skip_res):
            continue
        if line in seen:
            continue
        seen.add(line)
        result.append(line)

    with open(CLEAN_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(result))

    print(f"✅  Clean data → '{CLEAN_FILE}' ({len(result)} lines)\n")


# ══════════════════════════════════════════════════════════════
#  STEP 3 — BUILD FAISS INDEX
# ══════════════════════════════════════════════════════════════
def build_index():
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document

    print("🔨  Building FAISS vector index …")

    with open(CLEAN_FILE, "r", encoding="utf-8") as f:
        text = f.read()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    chunks = splitter.split_text(text)
    docs   = [Document(page_content=c) for c in chunks]

    print(f"  → {len(docs)} chunks created, embedding now …")

    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    db         = FAISS.from_documents(docs, embeddings)
    db.save_local(FAISS_DIR)

    print(f"✅  FAISS index saved to '{FAISS_DIR}/'\n")


# ══════════════════════════════════════════════════════════════
#  STEP 4 — PERIYAR CHAT LOOP
# ══════════════════════════════════════════════════════════════

PERIYAR_SYSTEM_PROMPT = """
You are Periyar, a warm and knowledgeable student assistant for
Periyar Maniammai Institute of Science & Technology (PMIST / PMU),
located in Thanjavur, Tamil Nadu, India.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHO YOU ARE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You are like a friendly senior student or helpful staff member at PMIST.
You genuinely care about helping students, parents, and visitors.
You speak naturally and warmly — not like a robot reading a manual.

Never say "I am an AI" or "I am a language model."
If someone asks if you're a bot, respond naturally:
e.g. "Haha, nope! Just someone who really loves helping people with
PMIST stuff 😄 What can I do for you?"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR PERSONALITY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Warm, friendly, and conversational — like a helpful senior student
- Encouraging — especially to new or confused students
- If asked in Tamil or Tanglish → reply in friendly Tanglish/Tamil mix
- Honest — never make up fees, cut-offs, or details not in context
- Use natural phrases: "Sure!", "Great question!", "Absolutely!"
- Mix prose and lists naturally — don't just bullet-dump everything

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT YOU KNOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Answer ONLY from the CONTEXT provided below (scraped from pmu.edu).

- Answer clearly in the context → respond confidently
- Partially in context → share what you know, be honest about gaps
- Not in context → say:
  "I don't have that specific detail right now — I'd recommend visiting
  pmu.edu directly or contacting the admissions office. They'll have the
  most accurate info! 😊"
- Never fabricate course fees, cut-off marks, or exam dates

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADMISSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
If someone asks about admissions:
- Share what's in context (courses, eligibility, links)
- Be encouraging and reassuring — admissions can be stressful!
- Point them to: {base_url}/admission/RegistrationNew.aspx

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STUDENT SERVICES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For portal-related queries (results, fees, registration):
- Main portal: {student_portal}
- Fee payment: {student_portal}/termsandconditions.aspx
- Results: {student_portal}/
- Always reassure if they seem stressed about exams or results

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OFF-TOPIC QUESTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
If someone asks something unrelated to PMIST:
- Answer briefly and helpfully like a friendly human would
- Then gently bring back:
  "Anyway — is there anything about PMIST I can help you with? 😊"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EMOTIONAL INTELLIGENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Confused student → slow down, reassure them patiently
- Stressed about exams/results → acknowledge it first, then help
- Excited about joining → match their energy! 🎉
- Never be cold or dismissive

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FORMAT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Keep responses focused — don't dump everything at once
- Use bullet points only when listing multiple distinct items
- For single-answer questions → natural prose
- Max ~150 words unless the question genuinely needs more
- End with a follow-up question or helpful nudge when it feels natural

CONTEXT FROM PMIST WEBSITE:
─────────────────────────────
{{context}}
─────────────────────────────
""".format(base_url=BASE_URL, student_portal=STUDENT_PORTAL)


def chat():
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_community.vectorstores import FAISS
    from langchain_groq import ChatGroq
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

    if not Path(FAISS_DIR).exists():
        print("❌  No FAISS index found. Run without --chat-only first.")
        sys.exit(1)

    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        print("❌  GROQ_API_KEY not found in .env file.")
        sys.exit(1)

    print("🔄  Loading PMIST vector index …")
    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    db         = FAISS.load_local(
        FAISS_DIR, embeddings, allow_dangerous_deserialization=True
    )

    llm = ChatGroq(
        model=LLM_MODEL,
        api_key=groq_key,
        temperature=0.6,
        max_tokens=512,
    )

    print("\n" + "━" * 56)
    print("  🎓  Hi! I'm Periyar, your PMIST assistant.")
    print("  Ask me anything about admissions, courses,")
    print("  student services, exams, or campus life!")
    print("  (type 'exit' or 'bye' to leave)")
    print("━" * 56 + "\n")

    conversation_history = []

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nPeriyar: Take care! All the best with your studies! 🎓\n")
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "bye", "quit", "goodbye"}:
            print(
                "\nPeriyar: It was great chatting! Best of luck with "
                "everything at PMIST 💪🎓 Bye for now!\n"
            )
            break

        # Retrieve relevant chunks from FAISS
        retrieved_docs = db.similarity_search(user_input, k=TOP_K)
        context        = "\n\n".join(d.page_content for d in retrieved_docs)

        # Build messages
        system_msg = SystemMessage(
            content=PERIYAR_SYSTEM_PROMPT.replace("{context}", context)
        )
        messages = [system_msg] + conversation_history + [
            HumanMessage(content=user_input)
        ]

        try:
            response = llm.invoke(messages)
            reply    = response.content.strip()
        except Exception as e:
            reply = (
                "Aiyo, something went wrong on my side 😅 "
                "Try again in a moment?"
            )
            print(f"  [LLM error: {e}]")

        print(f"\nPeriyar: {reply}\n")

        conversation_history.append(HumanMessage(content=user_input))
        conversation_history.append(AIMessage(content=reply))
        if len(conversation_history) > 12:
            conversation_history = conversation_history[-12:]


# ══════════════════════════════════════════════════════════════
#  ENTRYPOINT
# ══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="Periyar — PMIST AI Assistant"
    )
    parser.add_argument(
        "--chat-only",
        action="store_true",
        help="Skip scraping/indexing; load existing FAISS index and chat."
    )
    parser.add_argument(
        "--scrape-only",
        action="store_true",
        help="Only scrape and index; don't start the chat loop."
    )
    args = parser.parse_args()

    if args.chat_only:
        chat()
    elif args.scrape_only:
        scrape_website()
        clean_data()
        build_index()
        print("✅  Done! Run with --chat-only to start chatting.\n")
    else:
        scrape_website()
        clean_data()
        build_index()
        chat()
 
if __name__ == "__main__":
    main()