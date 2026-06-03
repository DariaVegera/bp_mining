import argparse
import json
import os
from pathlib import Path
import time
import requests
from anthropic import Anthropic
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]

PROMPT_PATH = ROOT_DIR / "prompts" / "interview_to_process_json.txt"
OUTPUT_PATH = ROOT_DIR / "output" / "process.json"

DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
DEFAULT_OPENROUTER_MODEL = "openrouter/free"


def call_anthropic(prompt: str, interview_text: str, model: str) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")

    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to .env or environment variables."
        )

    client = Anthropic(api_key=api_key)

    response = client.messages.create(
        model=model,
        max_tokens=4000,
        temperature=0,
        system=prompt,
        messages=[
            {
                "role": "user",
                "content": interview_text,
            }
        ],
    )

    return response.content[0].text


def call_openrouter(prompt: str, interview_text: str, model: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to .env or environment variables."
        )

    fallback_models = [
        model,
        "openai/gpt-oss-120b:free",
        "qwen/qwen3-coder:free",
        "qwen/qwen3-next-80b-a3b-instruct:free",
        "openrouter/free",
    ]

    # убираем дубли, сохраняя порядок
    fallback_models = list(dict.fromkeys(fallback_models))

    retry_statuses = {429, 500, 502, 503, 504}
    max_retries_per_model = 2

    last_error = None

    for current_model in fallback_models:
        for attempt in range(1, max_retries_per_model + 1):
            print(
                f"Calling OpenRouter model={current_model}, "
                f"attempt={attempt}/{max_retries_per_model}"
            )

            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "X-OpenRouter-Title": "bp-mining",
                },
                json={
                    "model": current_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": prompt,
                        },
                        {
                            "role": "user",
                            "content": interview_text,
                        },
                    ],
                    "temperature": 0,
                    "max_tokens": 4000,
                },
                timeout=120,
            )

            if response.status_code in retry_statuses:
                last_error = (
                    f"OpenRouter failed for model={current_model}: "
                    f"{response.status_code} {response.text}"
                )

                retry_after = response.headers.get("Retry-After")

                try:
                    sleep_seconds = int(float(retry_after)) if retry_after else 15
                except ValueError:
                    sleep_seconds = 15

                print(last_error)

                if attempt < max_retries_per_model:
                    print(f"Retry after {sleep_seconds} seconds...")
                    time.sleep(sleep_seconds)
                    continue

                print(f"Switching to next fallback model...")
                break

            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise RuntimeError(
                    f"OpenRouter request failed: {response.status_code} {response.text}"
                ) from exc

            data = response.json()

            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError(f"Unexpected OpenRouter response format: {data}") from exc

    raise RuntimeError(f"All OpenRouter fallback models failed. Last error: {last_error}")


def extract_json(text: str) -> dict:
    """
    На случай если модель случайно вернет текст вокруг JSON,
    пробуем вырезать JSON по первой { и последней }.
    """
    text = text.strip()

    if text.startswith("```"):
        text = (
            text.replace("```json", "")
            .replace("```JSON", "")
            .replace("```", "")
            .strip()
        )

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError(f"LLM response does not contain JSON object:\n{text}")

    json_text = text[start : end + 1]

    try:
        return json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse JSON from LLM response:\n{json_text}") from exc


def validate_process_json(data: dict) -> None:
    required_top_keys = {"process_name", "lanes", "elements", "flows"}
    missing_keys = required_top_keys - set(data.keys())

    if missing_keys:
        raise ValueError(f"Missing top-level keys: {missing_keys}")

    if not isinstance(data["lanes"], list) or not data["lanes"]:
        raise ValueError("lanes must be non-empty list")

    if not isinstance(data["elements"], list) or not data["elements"]:
        raise ValueError("elements must be non-empty list")

    if not isinstance(data["flows"], list) or not data["flows"]:
        raise ValueError("flows must be non-empty list")

    for lane in data["lanes"]:
        for key in ["id", "name"]:
            if key not in lane:
                raise ValueError(f"Lane missing key {key}: {lane}")

    lane_ids = {lane["id"] for lane in data["lanes"]}
    element_ids = {element["id"] for element in data["elements"]}

    if len(element_ids) != len(data["elements"]):
        raise ValueError("Duplicate element ids found")

    start_events = [e for e in data["elements"] if e.get("type") == "startEvent"]
    end_events = [e for e in data["elements"] if e.get("type") == "endEvent"]

    if len(start_events) != 1:
        raise ValueError(f"Expected exactly 1 startEvent, got {len(start_events)}")

    if len(end_events) < 1:
        raise ValueError("Expected at least 1 endEvent")

    allowed_types = {"startEvent", "task", "exclusiveGateway", "endEvent"}

    for element in data["elements"]:
        for key in ["id", "type", "name", "lane_id"]:
            if key not in element:
                raise ValueError(f"Element missing key {key}: {element}")

        if element["lane_id"] not in lane_ids:
            raise ValueError(f"Unknown lane_id in element: {element}")

        if element["type"] not in allowed_types:
            raise ValueError(f"Unsupported element type: {element}")

    for flow in data["flows"]:
        for key in ["id", "source_id", "target_id", "condition"]:
            if key not in flow:
                raise ValueError(f"Flow missing key {key}: {flow}")

        if flow["source_id"] not in element_ids:
            raise ValueError(f"Unknown source_id in flow: {flow}")

        if flow["target_id"] not in element_ids:
            raise ValueError(f"Unknown target_id in flow: {flow}")

    gateways = [e for e in data["elements"] if e.get("type") == "exclusiveGateway"]

    for gateway in gateways:
        outgoing = [f for f in data["flows"] if f["source_id"] == gateway["id"]]

        if len(outgoing) < 2:
            raise ValueError(
                f"Gateway must have at least 2 outgoing flows: {gateway['id']}"
            )

        if any(f["condition"] in [None, ""] for f in outgoing):
            raise ValueError(
                f"Gateway outgoing flows must have conditions: {gateway['id']}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse raw interview text into process.json using LLM"
    )

    parser.add_argument(
        "input_file",
        type=str,
        help="Path to raw interview .txt file",
    )

    parser.add_argument(
        "--provider",
        type=str,
        choices=["anthropic", "openrouter"],
        default="openrouter",
        help="LLM provider: anthropic or openrouter",
    )

    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name. If not set, default model for selected provider is used.",
    )

    parser.add_argument(
        "--output",
        type=str,
        default=str(OUTPUT_PATH),
        help="Path to output process.json",
    )

    args = parser.parse_args()

    load_dotenv()

    input_path = Path(args.input_file)
    output_path = Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt file not found: {PROMPT_PATH}")

    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    interview_text = input_path.read_text(encoding="utf-8")

    if args.provider == "anthropic":
        model = args.model or os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)
        raw_answer = call_anthropic(prompt, interview_text, model)

    elif args.provider == "openrouter":
        model = args.model or os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL)
        raw_answer = call_openrouter(prompt, interview_text, model)

    else:
        raise ValueError(f"Unsupported provider: {args.provider}")

    process_data = extract_json(raw_answer)

    validate_process_json(process_data)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(process_data, f, ensure_ascii=False, indent=2)

    print(f"Provider: {args.provider}")
    print(f"Model: {model}")
    print(f"Saved process JSON to: {output_path}")


if __name__ == "__main__":
    main()