"""Quick key test. Run to see real Anthropic error."""
import json
import sys
from pathlib import Path

settings_file = Path(__file__).parent / "lead_vault_settings.json"
settings = json.loads(settings_file.read_text(encoding="utf-8"))

key = settings.get("anthropic_api_key", "")
print(f"Key length: {len(key)}")
print(f"Key prefix: {key[:20]}...")
print(f"Key suffix: ...{key[-6:]}")
print(f"Has whitespace: {key != key.strip()}")
print(f"Model in settings: {settings.get('ai_model')}")

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic package not installed. Run: pip install anthropic")
    sys.exit(1)

print(f"\nanthropic version: {anthropic.__version__}")
print("\nCalling API...")
try:
    client = anthropic.Anthropic(api_key=key.strip(), timeout=30)
    resp = client.messages.create(
        model=settings.get("ai_model") or "claude-sonnet-4-6",
        max_tokens=50,
        messages=[{"role": "user", "content": "Say hi."}],
    )
    print("SUCCESS:", resp.content[0].text)
except Exception as exc:
    print(f"FAILED: {type(exc).__name__}")
    print(f"Message: {exc}")
