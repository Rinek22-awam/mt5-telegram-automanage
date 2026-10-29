"""Ask Gemini to read the price labels off a signal chart image."""
import json
import logging

log = logging.getLogger(__name__)

PROMPT = """You read trading-signal chart screenshots (TradingView). Report ONLY what is written
on the image. Do not analyse the market and do not guess numbers.

The signal is drawn as horizontal lines, each with a price label in parentheses next to it.
Line colour gives the role:
- RED line = stop loss
- BLUE line(s) = entry (there may be one or two)
- BLACK / dark line(s) = take profit targets
Ignore the price scale on the right edge, the current-price marker and the candles.

Copy every label exactly as printed, as text, keeping its dots and commas
(e.g. "3.987,260" or "112,450.5"). Also copy a ticker/symbol if one is written on the
image (e.g. "XAUUSD", "BTCUSDT"), else "".

Answer with JSON only:
{"is_signal": true/false,      // false if the image has no such coloured signal lines
 "entries": ["..."],           // blue labels
 "sl": "...",                  // red label, "" if none
 "tps": ["..."],               // black labels
 "symbol_text": "...",
 "highrisk": true/false}       // true only if the image itself says high risk
"""


class GeminiReader:
    def __init__(self, api_key: str, model: str):
        from google import genai
        from google.genai import types
        self.client, self.types, self.model = genai.Client(api_key=api_key), types, model

    def read(self, image: bytes, mime: str = "image/jpeg") -> dict:
        t = self.types
        resp = self.client.models.generate_content(
            model=self.model,
            contents=[t.Part.from_bytes(data=image, mime_type=mime), PROMPT],
            config=t.GenerateContentConfig(temperature=0, response_mime_type="application/json"))
        text = (resp.text or "").strip()
        log.info("gemini: %s", text)
        return parse_reply(text)


def parse_reply(text: str) -> dict:
    """Model reply -> dict. Tolerates ```json fences around the JSON."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):]
    data = json.loads(t[t.find("{"): t.rfind("}") + 1])
    return data if isinstance(data, dict) else {}
