import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional
import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import requests
import streamlit as st
from dotenv import load_dotenv
import streamlit as st
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT_DIR / "output"
UPLOADS_DIR = OUTPUT_DIR / "uploads"

PROCESS_JSON_PATH = OUTPUT_DIR / "process.json"
PROCESS_BPMN_PATH = OUTPUT_DIR / "process.bpmn"
TRANSCRIPT_PATH = OUTPUT_DIR / "transcript.txt"

load_dotenv(ROOT_DIR / ".env")

provider = "openrouter"
model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")
transcribe_model = os.getenv(
    "OPENROUTER_TRANSCRIBE_MODEL",
    "openai/gpt-4o-mini-transcribe",
)

# ============================================================
# UI config
# ============================================================

st.set_page_config(
    page_title="AI BPMN Process Miner",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="collapsed",
)


st.markdown(
    """
    <style>
        .stApp {
            background: linear-gradient(180deg, #f5fbff 0%, #ffffff 45%);
            color: #102a43;
        }

        section[data-testid="stSidebar"] {
            display: none;
        }

        .main-card {
            background: #ffffff;
            padding: 24px 28px;
            border-radius: 18px;
            border: 1px solid #d6ecff;
            box-shadow: 0 8px 24px rgba(45, 134, 209, 0.08);
            margin-bottom: 18px;
        }

        .hero-title {
            font-size: 38px;
            font-weight: 800;
            color: #0f609b;
            margin-bottom: 12px;
        }

        .blue-badge {
            display: inline-block;
            background: #e6f6ff;
            color: #0967d2;
            border: 1px solid #bae3ff;
            padding: 6px 12px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 600;
            margin-right: 8px;
            margin-bottom: 6px;
        }

        .success-box {
            background: #ecfdf5;
            border: 1px solid #a7f3d0;
            color: #065f46;
            padding: 12px 16px;
            border-radius: 12px;
            font-weight: 600;
            margin-top: 14px;
        }

        .warning-box {
            background: #fffbea;
            border: 1px solid #fce588;
            color: #8d2b0b;
            padding: 12px 16px;
            border-radius: 12px;
            font-weight: 600;
            margin-top: 14px;
        }

        div.stButton > button:first-child {
            background: #0ea5e9;
            color: white;
            border-radius: 12px;
            border: none;
            padding: 0.75rem 1.2rem;
            font-weight: 700;
            font-size: 16px;
        }

        div.stButton > button:first-child:hover {
            background: #0284c7;
            color: white;
            border: none;
        }

        div[data-testid="stFileUploader"] {
            background: #f0f9ff;
            border: 1px dashed #7dd3fc;
            border-radius: 14px;
            padding: 10px;
        }

        textarea {
            border-radius: 12px !important;
        }

        h2, h3 {
            color: #102a43;
        }

        .block-container {
            padding-top: 2.5rem;
            padding-bottom: 2.5rem;
            max-width: 1180px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# Helpers
# ============================================================

def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def run_command(cmd: list[str]) -> tuple[bool, str]:
    result = subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
    )

    output = ""

    if result.stdout:
        output += result.stdout

    if result.stderr:
        output += "\n" + result.stderr

    return result.returncode == 0, output.strip()


def save_text_to_temp_file(text: str) -> Path:
    ensure_dirs()

    input_path = UPLOADS_DIR / "streamlit_input.txt"
    input_path.write_text(text, encoding="utf-8")

    return input_path


def save_uploaded_audio(uploaded_file) -> Path:
    ensure_dirs()

    suffix = Path(uploaded_file.name).suffix
    audio_path = UPLOADS_DIR / f"uploaded_audio{suffix}"

    audio_path.write_bytes(uploaded_file.getvalue())

    return audio_path


def get_audio_format(audio_path: Path) -> str:
    suffix = audio_path.suffix.lower().replace(".", "")

    if suffix == "mpeg":
        return "mp3"

    supported_formats = {
        "wav",
        "mp3",
        "flac",
        "m4a",
        "ogg",
        "webm",
        "aac",
        "mp4",
    }

    if suffix not in supported_formats:
        raise ValueError(
            f"Unsupported audio format: {suffix}. "
            f"Supported formats: {sorted(supported_formats)}"
        )

    return suffix


def transcribe_audio(audio_path: Path) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to .env to use audio transcription."
        )

    audio_format = get_audio_format(audio_path)
    audio_base64 = base64.b64encode(audio_path.read_bytes()).decode("utf-8")

    response = requests.post(
        url="https://openrouter.ai/api/v1/audio/transcriptions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Title": "bp-mining",
        },
        json={
            "model": transcribe_model,
            "input_audio": {
                "data": audio_base64,
                "format": audio_format,
            },
            "language": "ru",
            "temperature": 0,
        },
        timeout=120,
    )

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"OpenRouter transcription failed: {response.status_code} {response.text}"
        ) from exc

    data = response.json()

    if "text" not in data:
        raise RuntimeError(f"Unexpected OpenRouter transcription response: {data}")

    return data["text"].strip()


def parse_validation_output(output: str) -> Optional[dict]:
    start = output.find("{")
    end = output.rfind("}")

    if start == -1 or end == -1:
        return None

    try:
        return json.loads(output[start : end + 1])
    except json.JSONDecodeError:
        return None


def read_file_bytes(path: Path) -> bytes:
    return path.read_bytes()


def read_file_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def run_full_pipeline(input_text: str) -> dict:
    input_path = save_text_to_temp_file(input_text)

    parse_cmd = [
        sys.executable,
        "scripts/llm_parse_interview.py",
        str(input_path),
        "--provider",
        provider,
    ]

    if model:
        parse_cmd.extend(["--model", model])

    ok_parse, parse_log = run_command(parse_cmd)

    if not ok_parse:
        return {
            "ok": False,
            "stage": "LLM parsing",
            "log": parse_log,
        }

    ok_bpmn, bpmn_log = run_command(
        [
            sys.executable,
            "scripts/generate_bpmn.py",
        ]
    )

    if not ok_bpmn:
        return {
            "ok": False,
            "stage": "BPMN generation",
            "log": parse_log + "\n\n" + bpmn_log,
        }

    ok_validate, validate_log = run_command(
        [
            sys.executable,
            "scripts/validate_bpmn.py",
        ]
    )

    if not ok_validate:
        return {
            "ok": False,
            "stage": "BPMN validation",
            "log": parse_log + "\n\n" + bpmn_log + "\n\n" + validate_log,
        }

    validation_json = parse_validation_output(validate_log)

    return {
        "ok": True,
        "stage": "done",
        "log": parse_log + "\n\n" + bpmn_log + "\n\n" + validate_log,
        "validation": validation_json,
    }


# ============================================================
# Header
# ============================================================

st.markdown(
    """
    <div class="main-card">
        <div class="hero-title">AI BPMN Process Miner</div>
        <span class="blue-badge">Text input</span>
        <span class="blue-badge">Audio upload</span>
        <span class="blue-badge">LLM → BPMN</span>
        <span class="blue-badge">Validation</span>
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# Input block
# ============================================================

st.markdown('<div class="main-card">', unsafe_allow_html=True)
st.subheader("Введите текст интервью или загрузите аудио")

tab_text, tab_audio = st.tabs(["📝 Текст интервью", "🎧 Аудио интервью"])

input_text = ""

with tab_text:
    example_text = ""

    example_path = ROOT_DIR / "examples" / "interview_vacation_raw.txt"
    if example_path.exists():
        example_text = example_path.read_text(encoding="utf-8")

    input_text = st.text_area(
        label="Текст интервью",
        value=example_text,
        height=330,
        placeholder=(
            "Вставьте сюда интервью с сотрудником: кто участвует, "
            "какие шаги процесса, какие условия и развилки..."
        ),
        label_visibility="collapsed",
    )

with tab_audio:
    uploaded_audio = st.file_uploader(
        "Загрузите аудио",
        type=["mp3", "wav", "m4a", "mp4", "mpeg", "webm", "flac", "ogg", "aac"],    )

    if uploaded_audio is not None:
        st.audio(uploaded_audio)

        if st.button("🎙️ Расшифровать аудио"):
            try:
                with st.spinner("Расшифровываю аудио..."):
                    audio_path = save_uploaded_audio(uploaded_audio)
                    transcript = transcribe_audio(audio_path)
                    TRANSCRIPT_PATH.write_text(transcript, encoding="utf-8")
                    st.session_state["transcript"] = transcript

                st.success("Аудио успешно расшифровано")
            except Exception as exc:
                st.error(f"Ошибка транскрибации: {exc}")

    transcript_text = st.session_state.get("transcript", "")

    input_text_audio = st.text_area(
        label="Текст после транскрибации",
        value=transcript_text,
        height=280,
        placeholder=(
            "Здесь появится текст после расшифровки аудио. "
            "Его можно отредактировать перед генерацией BPMN."
        ),
        label_visibility="collapsed",
    )

    if input_text_audio.strip():
        input_text = input_text_audio

st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# Run pipeline
# ============================================================

st.markdown('<div class="main-card">', unsafe_allow_html=True)
st.subheader("Сгенерировать BPMN")

run_clicked = st.button("🚀 Generate BPMN", use_container_width=True)

if run_clicked:
    if not input_text.strip():
        st.error("Сначала введите текст интервью или расшифруйте аудио.")
    else:
        with st.spinner("Генерирую бизнес-процесс..."):
            result = run_full_pipeline(input_text=input_text)

        st.session_state["pipeline_result"] = result

        if result["ok"]:
            st.markdown(
                '<div class="success-box">✅ BPMN успешно сгенерирован и прошёл валидацию</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="warning-box">❌ Ошибка на этапе: {result["stage"]}</div>',
                unsafe_allow_html=True,
            )

st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# Results
# ============================================================

result = st.session_state.get("pipeline_result")

if result:
    st.markdown('<div class="main-card">', unsafe_allow_html=True)
    st.subheader("Результат")

    if result.get("validation"):
        stats = result["validation"].get("stats", {})

        c1, c2, c3, c4 = st.columns(4)

        with c1:
            st.metric("Elements", stats.get("elements_in_bpmn", "-"))

        with c2:
            st.metric("Flows", stats.get("flows_in_bpmn", "-"))

        with c3:
            st.metric("Start events", stats.get("start_events", "-"))

        with c4:
            st.metric("End events", stats.get("end_events", "-"))

    download_cols = st.columns(3)

    with download_cols[0]:
        if PROCESS_JSON_PATH.exists():
            st.download_button(
                label="⬇️ Скачать process.json",
                data=read_file_text(PROCESS_JSON_PATH),
                file_name="process.json",
                mime="application/json",
                use_container_width=True,
            )

    with download_cols[1]:
        if PROCESS_BPMN_PATH.exists():
            st.download_button(
                label="⬇️ Скачать process.bpmn",
                data=read_file_bytes(PROCESS_BPMN_PATH),
                file_name="process.bpmn",
                mime="application/xml",
                use_container_width=True,
            )

    with download_cols[2]:
        if TRANSCRIPT_PATH.exists():
            st.download_button(
                label="⬇️ Скачать transcript.txt",
                data=read_file_text(TRANSCRIPT_PATH),
                file_name="transcript.txt",
                mime="text/plain",
                use_container_width=True,
            )

    st.divider()

    tab_json, tab_bpmn, tab_logs = st.tabs(["process.json", "process.bpmn", "logs"])

    with tab_json:
        if PROCESS_JSON_PATH.exists():
            st.json(json.loads(read_file_text(PROCESS_JSON_PATH)))
        else:
            st.warning("process.json пока не найден")

    with tab_bpmn:
        if PROCESS_BPMN_PATH.exists():
            st.code(read_file_text(PROCESS_BPMN_PATH), language="xml")
        else:
            st.warning("process.bpmn пока не найден")

    with tab_logs:
        st.code(result.get("log", ""), language="text")

    st.markdown("</div>", unsafe_allow_html=True)