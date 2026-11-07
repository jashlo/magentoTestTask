"""Browser automation scenario and video recorder for the Magento test task."""

import os
import re
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

PATH_TO_VIDEO_FOLDER = "./video"


_CURSOR_INIT_SCRIPT = r"""(() => {
  if (window.__qscriptCursorInstalled) return;
  window.__qscriptCursorInstalled = true;

  const install = () => {
    if (!document.documentElement || document.getElementById('__qscript_cursor_layer')) return;
    const style = document.createElement('style');
    style.id = '__qscript_cursor_style';
    style.textContent = `
      html, html * { cursor: none !important; }
      #__qscript_cursor_layer {
        position: fixed; left: 0; top: 0; width: 0; height: 0;
        z-index: 2147483647; pointer-events: none !important;
      }
      #__qscript_cursor_halo {
        position: absolute; width: 64px; height: 64px; border-radius: 50%;
        left: -32px; top: -32px; background: rgba(255, 220, 0, .34);
        pointer-events: none;
      }
      #__qscript_cursor_arrow {
        position: absolute; left: -2px; top: -2px; width: 32px; height: 32px;
        overflow: visible; pointer-events: none;
        filter: drop-shadow(0 1px 1px rgba(0,0,0,.22));
      }
      .__qscript_ripple {
        position: fixed; width: 12px; height: 12px; border-radius: 50%;
        border: 3px solid rgba(255, 205, 0, .95); background: rgba(255, 220, 0, .18);
        transform: translate(-50%, -50%) scale(.25); opacity: 1;
        z-index: 2147483646; pointer-events: none;
        animation: __qscript_ripple_anim 650ms ease-out forwards;
      }
      @keyframes __qscript_ripple_anim {
        to { transform: translate(-50%, -50%) scale(2.7); opacity: 0; }
      }
      #__qscript_callout {
        position: fixed; z-index: 2147483645; left: 50%; top: 28px;
        transform: translateX(-50%); padding: 12px 20px; border: 2px solid #111;
        border-radius: 4px; font: 16pt Arial, sans-serif; color: #111;
        background: #ffe34d; box-shadow: 0 3px 12px rgba(0,0,0,.2);
        max-width: 80vw; width: max-content; pointer-events: none;
        opacity: 0; transition: opacity 2s ease;
      }
    `;
    (document.head || document.documentElement).appendChild(style);

    const layer = document.createElement('div');
    layer.id = '__qscript_cursor_layer';
    layer.innerHTML = `
      <div id="__qscript_cursor_halo"></div>
      <svg id="__qscript_cursor_arrow" viewBox="0 0 32 32" aria-hidden="true">
        <path d="M2 1 L2 26 L9 19 L14 30 L19 28 L14 17 L25 17 Z"
          fill="#fff" stroke="#111" stroke-width="1.8"
          stroke-linejoin="round" />
      </svg>`;
    document.documentElement.appendChild(layer);

    const move = (x, y) => {
      layer.style.transform = `translate(${x}px, ${y}px)`;
    };
    document.addEventListener('mousemove', event => move(event.clientX, event.clientY), true);
    document.addEventListener('click', event => {
      const ripple = document.createElement('div');
      ripple.className = '__qscript_ripple';
      ripple.style.left = event.clientX + 'px';
      ripple.style.top = event.clientY + 'px';
      document.documentElement.appendChild(ripple);
      window.setTimeout(() => ripple.remove(), 750);
    }, true);
    move(24, 24);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install, { once: true });
  } else {
    install();
  }
})();"""


def _safe_filename(value):
    """Return a portable filename stem without path separators."""
    value = str(value or "company").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = value.strip("._-")
    return value or "company"


def _smooth_move(page, x, y, steps=28, delay_ms=14):
    """Move the real Playwright mouse in small steps for a visible glide."""
    page.mouse.move(x, y, steps=steps)
    page.wait_for_timeout(delay_ms)


def ShowCallout(page, text, bgColor="yellow", textColor="black", fade=True):
    """Display an optional on-screen message; fade in/out takes ~2s each."""
    page.evaluate(
        """({text, bgColor, textColor, fade}) => {
          let box = document.getElementById('__qscript_callout');
          if (!box) {
            box = document.createElement('div');
            box.id = '__qscript_callout';
            document.documentElement.appendChild(box);
          }
          box.textContent = text;
          box.style.backgroundColor = bgColor;
          box.style.color = textColor;
          box.style.transition = fade ? 'opacity 2s ease' : 'none';
          requestAnimationFrame(() => { box.style.opacity = '1'; });
        }""",
        {"text": str(text), "bgColor": bgColor, "textColor": textColor, "fade": bool(fade)},
    )
    if fade:
        page.wait_for_timeout(2100)

    page.evaluate(
        """(fade) => {
          const box = document.getElementById('__qscript_callout');
          if (!box) return;
          box.style.opacity = '0';
          if (!fade) box.remove();
          else window.setTimeout(() => box.remove(), 2100);
        }""",
        bool(fade),
    )
    if fade:
        page.wait_for_timeout(2100)


def CaptureVideo_Magento(
    url,
    company_name,
    language,
    country,
    postcode,
    city,
    street,
    house_no,
):
    """Run the sample search flow and return the absolute .webm path."""
    del language, country, postcode, street, house_no  

    output_dir = Path(PATH_TO_VIDEO_FOLDER).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_dir = output_dir / "_playwright_tmp"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / (_safe_filename(company_name) + ".webm")

    browser = None
    context = None
    page = None
    video_path = None
    success = False

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                record_video_dir=str(temporary_dir),
                record_video_size={"width": 1280, "height": 720},
            )
            context.add_init_script(_CURSOR_INIT_SCRIPT)
            page = context.new_page()
            page.goto(str(url).strip(), wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(900)

            search_box = page.locator('textarea[name="q"]').first
            search_box.wait_for(state="visible", timeout=30000)
            box = search_box.bounding_box()
            if not box:
                raise RuntimeError("Search box is not visible or has no bounding box")
            target_x = box["x"] + box["width"] / 2
            target_y = box["y"] + box["height"] / 2
            _smooth_move(page, target_x, target_y, steps=35)
            search_box.click()

            query = "Magento developer in " + str(city or "London").strip()
            ShowCallout(page, "Searching: " + query, "#ffe34d", "#111111", True)
            for character in query:
                page.keyboard.type(character, delay=85)

            search_button = page.locator('form button[type="submit"]').first
            search_button.wait_for(state="visible", timeout=15000)
            button_box = search_button.bounding_box()
            if button_box:
                _smooth_move(
                    page,
                    button_box["x"] + button_box["width"] / 2,
                    button_box["y"] + button_box["height"] / 2,
                    steps=20,
                )
            search_button.click()

           
            results = page.locator('a[data-testid="result-title-a"]')
            results.first.wait_for(state="visible", timeout=45000)
            page.wait_for_timeout(700)
            result_box = results.first.bounding_box()
            if not result_box:
                raise RuntimeError("The first search result has no visible bounding box")
            _smooth_move(
                page,
                result_box["x"] + min(result_box["width"] / 2, 260),
                result_box["y"] + result_box["height"] / 2,
                steps=38,
            )
            results.first.click(timeout=20000)
            page.wait_for_timeout(1800)
            success = True

            video_path = page.video.path()
            context.close()  
            context = None
            browser.close()
            browser = None

        if video_path and Path(video_path).is_file():
            if final_path.exists():
                final_path.unlink()
            Path(video_path).replace(final_path)
            return str(final_path.resolve())
        raise RuntimeError("Playwright did not produce a video file")

    except Exception as exc:
        print("[ERROR] {}: {}".format(company_name, exc))
        return None
    finally:
        
        try:
            if context is not None:
                if page is not None:
                    try:
                        video_path = page.video.path()
                    except Exception:
                        pass
                context.close()
        except Exception:
            pass
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        
