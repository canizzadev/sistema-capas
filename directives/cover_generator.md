# Cover Generator Pipeline & Typography Specs (DO NOT MODIFY)

This directive documents the strict rules, Figma coordinates, typography, and fallback strategies for `execution/generate_cover.py`. **Never overwrite these mathematical values or logic without explicit user permission.**

## 1. AI Image Expansion (Gemini)
- **Library:** Must use the new `google-genai` SDK (`from google import genai`), NOT the deprecated `google.generativeai`.
- **Model:** `gemini-2.5-flash-image`.
- **Config:** Must enforce `response_modalities=["IMAGE"]` to return raw image bytes, and `aspect_ratio="16:9"`.
- **Input:** The PIL image must be temporarily saved as a JPEG byte array in memory before sending to the API.

## 2. Fallback Strategy (Mirror Blur)
If the API fails (e.g., Quota 429 or network error), do NOT stretch the image. Use the Mirror Blur technique:
- Canvas: 1920x1000.
- Background: A stretched version of the sharp image heavily blurred (`ImageFilter.GaussianBlur(radius=80)`).
- Foreground: The sharp image resized to 1000px height, positioned at `x = min(1920 * 0.60, 1920 - width)`.

## 3. Visual Composition & Coordinates
- **Gradient Overlay:** Must cover 60% of the screen (width = `1920 * 0.60`). Linear fade from Alpha 190 (75% opacity) at `x=0` to Alpha 0.
- **Base Alignment:** All left-aligned text and the button start strictly at `x = 320`.
- **Text Block (Specialty + Headline):** - Offset by `+27px` (starts at `x = 347`).
  - Has a 1px solid white (`#FFFFFF`) vertical line on the left, positioned exactly at `x = 320`.
- **Headline Word Wrap:** Must use the custom `balance_text` function to split the text, enforcing that the first line is always longer than or equal to the second line.
- **Optical Spacing:** Line height is `+10px`. The gap before the text block is `53px`, and the gap before the button is also `53px`.

## 4. The "Super Button" (Layered Border-Radius)
To properly render a 3px bottom border on a button with a 5px border-radius in Pillow, we use layered shapes:
1. **Glow:** Background rounded rectangle with 30% opacity of the lightened brand color, blurred by `36.5px`.
2. **Base (Border):** Full 305x81px rounded rectangle (radius 5px) in the darkened brand color.
3. **Gradient Fill:** A 305x78px rounded rectangle (radius 5px) with the horizontal gradient, pasted on top, leaving exactly 3px of the base visible at the bottom.
- **Icon:** Must load `static/seta.png` (22x22px). Do not attempt to draw the SVG via Pillow line vectors to avoid aliasing issues.

## 5. Typography Specs expected in `static/fonts/`
- **Name:** TheSeasons-Regular.ttf (102px, letter-spacing -3px).
- **Prefix:** Poppins-Regular.ttf (20px, uppercase).
- **Specialty:** Poppins-SemiBold.ttf (20px).
- **Headline:** Poppins-Regular.ttf (20px).
- **Button:** Poppins-Regular.ttf (18px).
- **City:** AtypDisplay-Regular.ttf (16px, 40% opacity, tracking 1).
