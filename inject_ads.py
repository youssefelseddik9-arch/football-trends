"""Inject the new Adsterra ad units + first-click-session system into every
existing post_*.html file in place. Designed to be idempotent: running it twice
does not duplicate the injected blocks."""

import os
import re
import glob
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

NATIVE_BANNER_BLOCK = """            <div class="widget ad-banner-widget">
                <span style="font-size:12px; color:#888; font-weight:bold; margin-bottom:10px;" data-i18n="ad_label">Featured Ad - Adsterra</span>
                <script async="async" data-cfasync="false" src="https://pl30650962.effectivecpmnetwork.com/29fb4cec1b995ab1738cf1b8e766a785/invoke.js"></script>
                <div id="container-29fb4cec1b995ab1738cf1b8e766a785"></div>
            </div>"""

VIGNETTE_SCRIPT = '<script src="https://pl30650964.effectivecpmnetwork.com/53/f4/e7/53f4e7d63aacc82e63ee31788fa4a719.js" data-cfasync="false"></script>'
EXTRA_SCRIPT = '<script src="https://pl30650961.effectivecpmnetwork.com/09/c8/a5/09c8a54b7a416983887fdd259ef81ee3.js" data-cfasync="false"></script>'

FIRST_CLICK_SNIPPET = """
        (function setupFirstClickAd() {
            const AD_LINK = "https://www.effectivecpmnetwork.com/pkpt9jk71e?key=c3a154702180e63a6b4f714b3db126f2";
            const FLAG = "gp_ad_clicked";
            const DISMISS_FLAG = "gp_ad_dismissed";
            if (sessionStorage.getItem(FLAG)) { return; }
            let triggered = false;

            function buildOverlay(targetHref) {
                const ov = document.createElement('div');
                ov.id = 'gp-ad-overlay';
                ov.style.cssText = [
                    'position:fixed','inset:0','z-index:2147483647',
                    'background:rgba(15,23,42,.86)','backdrop-filter:blur(6px)',
                    'display:flex','align-items:center','justify-content:center',
                    'padding:24px','box-sizing:border-box','text-align:center',
                    'color:#e2e8f0','font-family:inherit','animation:gpFadeIn .18s ease-out'
                ].join(';');

                const card = document.createElement('div');
                card.style.cssText = [
                    'position:relative','max-width:520px','width:100%',
                    'background:#0f172a','border:1px solid #334155',
                    'border-radius:14px','padding:36px 26px 26px','box-shadow:0 20px 60px rgba(0,0,0,.55)'
                ].join(';');

                const closeBtn = document.createElement('button');
                closeBtn.setAttribute('aria-label','Close ad and back to site');
                closeBtn.innerHTML = '&times;';
                closeBtn.style.cssText = [
                    'position:absolute','top:8px','right:12px','width:38px','height:38px',
                    'border:none','background:rgba(226,232,240,.10)','color:#e2e8f0',
                    'font-size:24px','line-height:1','border-radius:50%','cursor:pointer',
                    'transition:background .15s ease, transform .15s ease'
                ].join(';');
                closeBtn.onmouseenter = () => { closeBtn.style.background = '#dc2626'; closeBtn.style.transform = 'scale(1.08)'; };
                closeBtn.onmouseleave = () => { closeBtn.style.background = 'rgba(226,232,240,.10)'; closeBtn.style.transform = 'scale(1)'; };
                card.appendChild(closeBtn);

                const label = document.createElement('div');
                label.textContent = 'Sponsored Content';
                label.style.cssText = 'font-size:11px;letter-spacing:1.4px;text-transform:uppercase;color:#94a3b8;margin-bottom:14px;font-weight:700;';
                card.appendChild(label);

                const h = document.createElement('div');
                h.textContent = 'Support GoalPulse';
                h.style.cssText = 'font-size:22px;font-weight:800;color:#fff;margin-bottom:8px;';
                card.appendChild(h);

                const p = document.createElement('p');
                p.textContent = 'Your click keeps our football coverage free. Opening the sponsor in a new tab\\u2026';
                p.style.cssText = 'font-size:14px;line-height:1.6;color:#cbd5e1;margin-bottom:18px;';
                card.appendChild(p);

                const sponsor = document.createElement('a');
                sponsor.href = AD_LINK;
                sponsor.target = '_blank';
                sponsor.rel = 'noopener';
                sponsor.textContent = 'Visit Sponsor \\u2192';
                sponsor.style.cssText = 'display:inline-block;background:#dc2626;color:#fff;padding:11px 22px;border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;';
                card.appendChild(sponsor);

                const hint = document.createElement('div');
                hint.textContent = 'Tap \\u00d7 to close and continue reading';
                hint.style.cssText = 'margin-top:16px;font-size:12px;color:#64748b;';
                card.appendChild(hint);

                ov.appendChild(card);
                document.body.appendChild(ov);

                function dismiss(returnToSite) {
                    sessionStorage.setItem(DISMISS_FLAG, '1');
                    const el = document.getElementById('gp-ad-overlay');
                    if (el) { el.style.opacity = '0'; el.style.transition = 'opacity .15s ease'; setTimeout(() => el.remove(), 150); }
                    document.body.style.overflow = '';
                    if (returnToSite) {
                        if (window.location.href.includes('post_')) {
                            window.scrollTo({top:0, behavior:'smooth'});
                        }
                    }
                }

                closeBtn.onclick = (ev) => { ev.preventDefault(); ev.stopPropagation(); dismiss(true); };
                ov.addEventListener('click', (ev) => { if (ev.target === ov) { dismiss(true); } });
                document.body.style.overflow = 'hidden';
                return dismiss;
            }

            function triggerAd(href) {
                if (triggered) { return; }
                triggered = true;
                const dismiss = buildOverlay(href);
                try {
                    const w = window.open(AD_LINK, "_blank");
                    if (w) { w.blur(); window.focus(); }
                } catch (e) {}
                sessionStorage.setItem(FLAG, "1");
                setTimeout(function() {
                    dismiss(false);
                    if (href && href !== "#" && !href.startsWith("javascript:")) {
                        window.location.href = href;
                    }
                }, 6000);
            }
            document.addEventListener("click", function(e) {
                const a = e.target.closest("a");
                if (!a) { return; }
                const href = a.getAttribute("href");
                if (!href || href === "#" || href.startsWith("javascript:")) { return; }
                e.preventDefault();
                triggerAd(href);
            }, { once: true });
        })();
"""

AD_LINK = "https://www.effectivecpmnetwork.com/pkpt9jk71e?key=c3a154702180e63a6b4f714b3db126f2"


def has_block(content, needle):
    return needle in content


def replace_native_banner(content):
    """Replace any existing adsterra ad-banner-widget block (old or new) with the new one."""
    pattern = re.compile(
        r'<div class="widget ad-banner-widget">[\s\S]*?</div>\s*</div>\s*</div>',
        re.IGNORECASE
    )
    # Remove all existing ad-banner-widget blocks (old pl30532743 + new pl30650962)
    content = re.sub(
        r'<div class="widget ad-banner-widget">[\s\S]*?(?=<div class="widget"|\s*</aside>|\s*</main>)',
        '',
        content,
        flags=re.IGNORECASE
    )
    # Also remove a possible orphan trailing </div> left from above
    return content


def add_scripts_and_snippet(content):
    """Insert the Vignette + extra scripts + first-click snippet just before </body>."""
    if has_block(content, VIGNETTE_SCRIPT):
        return content
    insertion = "\n    " + VIGNETTE_SCRIPT + "\n    " + EXTRA_SCRIPT + "\n" if VIGNETTE_SCRIPT not in content else ""
    parts = []
    if VIGNETTE_SCRIPT not in content:
        parts.append(VIGNETTE_SCRIPT)
    if EXTRA_SCRIPT not in content:
        parts.append(EXTRA_SCRIPT)
    scripts_blob = "\n    ".join(parts)

    snippet_block = "<script>" + FIRST_CLICK_SNIPPET + "    </script>\n"
    if "gp_ad_clicked" not in content:
        insertion_blob = "    " + scripts_blob + "\n" + snippet_block
    else:
        insertion_blob = "    " + scripts_blob + "\n"

    content = content.replace("</body>", insertion_blob + "</body>", 1)
    return content


def inject_ads():
    files = sorted(glob.glob(os.path.join(PROJECT_DIR, "post_*.html")), reverse=True)
    updated = 0
    for fpath in files:
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        original = content

        # 1. Replace old ad-banner-widget block (pl30532743 ...) with new native banner
        if "pl30532743" in content or "e0506d6c" in content:
            content = re.sub(
                r'<div class="widget ad-banner-widget">[\s\S]*?</div>\s*</div>',
                NATIVE_BANNER_BLOCK,
                content,
                count=1,
                flags=re.IGNORECASE
            )
            # Remove second possible duplicate (regex above may leave a stray one)
            content = re.sub(
                r'<div class="widget ad-banner-widget">[\s\S]*?(?=<div class="widget"|\s*</aside>|\s*</main>)',
                '',
                content,
                flags=re.IGNORECASE
            )

        # 2. Add Vignette + extra scripts + first-click snippet before </body>
        content = add_scripts_and_snippet(content)

        if content != original:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            updated += 1
            print(f"Injected ads into {os.path.basename(fpath)}")
    print(f"Injection complete. {updated} file(s) modified.")


if __name__ == "__main__":
    inject_ads()
