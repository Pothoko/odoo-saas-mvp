/**
 * AEI Guide Overlay — cursor virtual flotante que se mueve por la pantalla
 * mostrándole al usuario dónde hacer click, con un anillo pulsante en el
 * elemento objetivo y un globo de diálogo con la instrucción.
 *
 * No depende de web_tour: es un motor visual minimalista que corre tanto en
 * el website público como en el backend de Odoo. Los pasos se definen como
 * un array de { trigger, content, action, position, scroll } y se registran
 * por nombre de tour en `window.AEI_GUIDES`.
 */
(function () {
    "use strict";

    if (window.AEIGuide) return; // ya cargado

    const PENDING_KEY = "aei_pending_tour";
    const HIGHLIGHT_PAD = 6; // px de padding alrededor del target
    const CURSOR_ANIM_MS = 800;
    const RETRY_INTERVAL_MS = 250;
    const RETRY_MAX_MS = 8000;

    // ── Selector helpers ────────────────────────────────────────────────────

    function _stripContains(selector) {
        // Quita los `:contains(...)` que querySelector nativo no soporta.
        return selector.replace(/:contains\([^)]*\)/g, "").trim();
    }

    function _containsTexts(selector) {
        // Extrae los textos buscados dentro de `:contains("X")`.
        const out = [];
        const re = /:contains\(["']?([^"')]+)["']?\)/g;
        let m;
        while ((m = re.exec(selector))) out.push(m[1].toLowerCase());
        return out;
    }

    function findElement(trigger) {
        // Soporta lista de fallbacks separada por coma, y `:contains()`.
        const variants = trigger.split(",").map((s) => s.trim()).filter(Boolean);
        for (const raw of variants) {
            const css = _stripContains(raw);
            const texts = _containsTexts(raw);
            let candidates;
            try {
                candidates = css
                    ? Array.from(document.querySelectorAll(css))
                    : Array.from(document.querySelectorAll("*"));
            } catch (e) {
                continue; // selector inválido — siguiente variante
            }
            for (const el of candidates) {
                if (!_isVisible(el)) continue;
                if (texts.length) {
                    const t = (el.textContent || "").toLowerCase();
                    if (!texts.every((needle) => t.includes(needle))) continue;
                }
                return el;
            }
        }
        return null;
    }

    function _isVisible(el) {
        if (!el || !(el instanceof Element)) return false;
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return false;
        const style = getComputedStyle(el);
        if (style.visibility === "hidden" || style.display === "none") return false;
        return true;
    }

    // ── Engine ──────────────────────────────────────────────────────────────

    class AEIGuide {
        constructor() {
            this.overlay = null;
            this.cursor = null;
            this.ring = null;
            this.tooltip = null;
            this.tooltipText = null;
            this.btnSkip = null;
            this.btnNext = null;
            this.progress = null;
            this.steps = [];
            this.idx = -1;
            this.currentTarget = null;
            this._onTargetClick = this._onTargetClick.bind(this);
            this._onKey = this._onKey.bind(this);
            this._retryHandle = null;
            this._retryStarted = 0;
        }

        start(tourNameOrObj) {
            // Acepta nombre de tour registrado en window.AEI_GUIDES o el objeto directo.
            let tour;
            if (typeof tourNameOrObj === "string") {
                tour = (window.AEI_GUIDES || {})[tourNameOrObj];
                if (!tour) {
                    console.warn("AEIGuide: tour no registrado:", tourNameOrObj);
                    this._toast("No tengo guía para ese flujo todavía.");
                    return;
                }
            } else {
                tour = tourNameOrObj;
            }
            if (!tour.steps || !tour.steps.length) {
                this._toast("Esta guía aún no tiene pasos.");
                return;
            }
            this.steps = tour.steps;
            this.idx = -1;
            this._mount();
            this._next();
        }

        stop() {
            this._clearRetry();
            this._unbindTarget();
            if (this.overlay) {
                this.overlay.classList.add("aei-guide-fade-out");
                setTimeout(() => {
                    if (this.overlay) this.overlay.remove();
                    this.overlay = null;
                }, 250);
            }
            document.removeEventListener("keydown", this._onKey, true);
        }

        // ── Build / mount ──────────────────────────────────────────────────

        _mount() {
            if (this.overlay) return;
            const root = document.createElement("div");
            root.className = "aei-guide-root";
            root.innerHTML = `
                <div class="aei-guide-ring"></div>
                <div class="aei-guide-cursor">
                    <svg viewBox="0 0 24 24" width="32" height="32">
                        <defs>
                            <radialGradient id="aei-cur-g" cx="50%" cy="50%" r="50%">
                                <stop offset="0%" stop-color="#ffffff" stop-opacity="0.95"/>
                                <stop offset="60%" stop-color="#9b6ab8" stop-opacity="0.9"/>
                                <stop offset="100%" stop-color="#714B67" stop-opacity="0.85"/>
                            </radialGradient>
                        </defs>
                        <path d="M4 2 L4 18 L9 14 L12 22 L15 21 L12 13 L19 13 Z"
                              fill="url(#aei-cur-g)" stroke="#3d2741"
                              stroke-width="1" stroke-linejoin="round"/>
                    </svg>
                </div>
                <div class="aei-guide-tooltip">
                    <div class="aei-guide-tooltip-arrow"></div>
                    <div class="aei-guide-tooltip-body">
                        <div class="aei-guide-tooltip-text"></div>
                        <div class="aei-guide-tooltip-row">
                            <span class="aei-guide-progress"></span>
                            <div class="aei-guide-actions">
                                <button class="aei-guide-skip" type="button">Salir</button>
                                <button class="aei-guide-next" type="button">Siguiente</button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(root);
            this.overlay = root;
            this.cursor = root.querySelector(".aei-guide-cursor");
            this.ring = root.querySelector(".aei-guide-ring");
            this.tooltip = root.querySelector(".aei-guide-tooltip");
            this.tooltipText = root.querySelector(".aei-guide-tooltip-text");
            this.btnSkip = root.querySelector(".aei-guide-skip");
            this.btnNext = root.querySelector(".aei-guide-next");
            this.progress = root.querySelector(".aei-guide-progress");
            this.btnSkip.addEventListener("click", () => this.stop());
            this.btnNext.addEventListener("click", () => this._next());
            document.addEventListener("keydown", this._onKey, true);
        }

        _onKey(ev) {
            if (ev.key === "Escape") {
                this.stop();
            } else if (ev.key === "ArrowRight" || ev.key === "Enter") {
                this._next();
            }
        }

        // ── Step loop ──────────────────────────────────────────────────────

        _next() {
            this._clearRetry();
            this._unbindTarget();
            this.idx++;
            if (this.idx >= this.steps.length) {
                this._finish();
                return;
            }
            const step = this.steps[this.idx];

            // Permitir navegación a una URL distinta antes del paso.
            if (step.url && window.location.pathname !== step.url) {
                try {
                    sessionStorage.setItem(
                        PENDING_KEY,
                        JSON.stringify({
                            steps: this.steps.slice(this.idx),
                            ts: Date.now(),
                        })
                    );
                } catch (e) {}
                window.location.href = step.url;
                return;
            }

            this._tryStep(step);
        }

        _tryStep(step) {
            const target = step.trigger ? findElement(step.trigger) : null;
            if (target) {
                this._showStep(step, target);
                return;
            }
            // Si no es bloqueante (info sin trigger), mostrar en el centro.
            if (step.action === "info" && !step.trigger) {
                this._showStep(step, null);
                return;
            }
            // Reintento por hasta RETRY_MAX_MS
            this._retryStarted = this._retryStarted || Date.now();
            if (Date.now() - this._retryStarted > RETRY_MAX_MS) {
                this._retryStarted = 0;
                console.warn("AEIGuide: no encontré target para paso", this.idx, step.trigger);
                // Skip al siguiente — no rompemos el flujo
                this._next();
                return;
            }
            this._retryHandle = setTimeout(() => this._tryStep(step), RETRY_INTERVAL_MS);
        }

        _showStep(step, target) {
            this._retryStarted = 0;
            this.tooltipText.textContent = step.content || "";
            this.progress.textContent = `${this.idx + 1} / ${this.steps.length}`;

            const action = step.action || "click";
            const isClick = action === "click" && target;
            this.btnNext.textContent = isClick ? "Sin clic" : "Siguiente";
            this.btnNext.style.display = "inline-block";

            if (target) {
                this.currentTarget = target;
                this._positionAroundTarget(target, step.position);
                if (isClick) {
                    target.addEventListener("click", this._onTargetClick, {
                        once: true,
                        capture: true,
                    });
                    target.classList.add("aei-guide-pulse-target");
                }
            } else {
                // Centro de la viewport.
                this._positionCenter();
                this.currentTarget = null;
            }
        }

        _onTargetClick() {
            // El usuario hizo lo que le pedimos — avanzar.
            setTimeout(() => this._next(), 400);
        }

        _unbindTarget() {
            if (this.currentTarget) {
                this.currentTarget.removeEventListener(
                    "click",
                    this._onTargetClick,
                    true
                );
                this.currentTarget.classList.remove("aei-guide-pulse-target");
                this.currentTarget = null;
            }
        }

        _clearRetry() {
            if (this._retryHandle) {
                clearTimeout(this._retryHandle);
                this._retryHandle = null;
            }
        }

        // ── Positioning ────────────────────────────────────────────────────

        _positionAroundTarget(target, position) {
            // Scroll into view smoothly antes de medir.
            try {
                target.scrollIntoView({ behavior: "smooth", block: "center" });
            } catch (e) {}
            // Pequeño delay para que termine el scroll antes de medir
            setTimeout(() => this._placeAt(target, position), 350);
        }

        _placeAt(target, position) {
            const rect = target.getBoundingClientRect();
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;

            // Ring sobre el target
            const r = this.ring;
            r.style.left = `${rect.left - HIGHLIGHT_PAD}px`;
            r.style.top = `${rect.top - HIGHLIGHT_PAD}px`;
            r.style.width = `${rect.width + 2 * HIGHLIGHT_PAD}px`;
            r.style.height = `${rect.height + 2 * HIGHLIGHT_PAD}px`;
            r.style.opacity = "1";

            // Cursor un poco abajo-a-la-derecha del target (como un mouse real)
            const curX = rect.right - 6;
            const curY = rect.bottom - 6;
            this.cursor.style.transform = `translate(${curX}px, ${curY}px)`;
            this.cursor.style.opacity = "1";

            // Tooltip: por defecto debajo del target, pero re-calcula si no entra.
            const tt = this.tooltip;
            tt.style.opacity = "1";
            tt.classList.remove("pos-top", "pos-left", "pos-right", "pos-bottom");
            const pos = position || (rect.bottom > window.innerHeight - 180 ? "top" : "bottom");
            tt.classList.add(`pos-${pos}`);

            // Medir tooltip después de asignar texto
            requestAnimationFrame(() => {
                const tRect = tt.getBoundingClientRect();
                let ttLeft, ttTop;
                if (pos === "top") {
                    ttLeft = cx - tRect.width / 2;
                    ttTop = rect.top - tRect.height - 16;
                } else if (pos === "left") {
                    ttLeft = rect.left - tRect.width - 16;
                    ttTop = cy - tRect.height / 2;
                } else if (pos === "right") {
                    ttLeft = rect.right + 16;
                    ttTop = cy - tRect.height / 2;
                } else {
                    ttLeft = cx - tRect.width / 2;
                    ttTop = rect.bottom + 16;
                }
                // Clamp dentro de la viewport
                ttLeft = Math.max(8, Math.min(window.innerWidth - tRect.width - 8, ttLeft));
                ttTop = Math.max(8, Math.min(window.innerHeight - tRect.height - 8, ttTop));
                tt.style.left = `${ttLeft}px`;
                tt.style.top = `${ttTop}px`;
            });
        }

        _positionCenter() {
            this.ring.style.opacity = "0";
            const cx = window.innerWidth / 2;
            const cy = window.innerHeight / 2;
            this.cursor.style.transform = `translate(${cx}px, ${cy}px)`;
            this.cursor.style.opacity = "0.6";
            const tt = this.tooltip;
            tt.style.opacity = "1";
            tt.classList.remove("pos-top", "pos-left", "pos-right", "pos-bottom");
            tt.classList.add("pos-bottom");
            requestAnimationFrame(() => {
                const tRect = tt.getBoundingClientRect();
                tt.style.left = `${cx - tRect.width / 2}px`;
                tt.style.top = `${cy + 30}px`;
            });
        }

        _finish() {
            this.tooltipText.textContent = "¡Listo! Eso es todo. Cualquier duda, volvé a abrirme.";
            this.progress.textContent = "✓";
            this.btnNext.style.display = "none";
            this.btnSkip.textContent = "Cerrar";
            this.ring.style.opacity = "0";
            const cx = window.innerWidth / 2;
            const cy = window.innerHeight / 2 - 100;
            this.cursor.style.transform = `translate(${cx}px, ${cy}px)`;
            this._positionCenter();
            setTimeout(() => {
                if (this.overlay) this.tooltipText.textContent &&
                    this.btnSkip.focus();
            }, 200);
        }

        _toast(msg) {
            // Mini toast — para cuando el tour no existe.
            const t = document.createElement("div");
            t.className = "aei-guide-toast";
            t.textContent = msg;
            document.body.appendChild(t);
            setTimeout(() => t.remove(), 3000);
        }
    }

    const instance = new AEIGuide();
    window.AEIGuide = instance;

    // Reanudar tour pendiente tras una redirección entre páginas.
    function tryResume() {
        let pending;
        try {
            pending = JSON.parse(sessionStorage.getItem(PENDING_KEY) || "null");
        } catch (e) {
            pending = null;
        }
        if (!pending?.steps) return;
        sessionStorage.removeItem(PENDING_KEY);
        setTimeout(() => instance.start({ steps: pending.steps }), 600);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", tryResume);
    } else {
        tryResume();
    }
})();
