/* GHOST — o Núcleo: anel de poeira em volta de uma estrela tapada (desenho animado em canvas).
   Usado pelo painel do PC e pelo app do celular:  const n = GhostNucleo.criar(canvas); n.estado("pensando"); */
(() => {
  "use strict";
  const calmo = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const ESTADOS = {
    espera:   { rotulo: "Em espera",      cor: "#9a8770", brilho: .42, giro: .25, raio: 1.00 },
    ouvindo:  { rotulo: "Ouvindo",        cor: "#e8b04b", brilho: .85, giro: .55, raio: 1.10 },
    pensando: { rotulo: "Pensando",       cor: "#ff8a3a", brilho: .95, giro: 1.7, raio: 1.02 },
    falando:  { rotulo: "Falando",        cor: "#ffb35c", brilho: .90, giro: .7,  raio: 1.05 },
    conversa: { rotulo: "Conversa ativa", cor: "#f0c46a", brilho: .62, giro: .4,  raio: 1.04 },
    dormindo: { rotulo: "Dormindo",       cor: "#5b4a3a", brilho: .14, giro: .08, raio: .92 },
    erro:     { rotulo: "Erro",           cor: "#e0503a", brilho: .80, giro: .9,  raio: 1.00 },
  };

  function criar(cv) {
    const cx = cv.getContext("2d");
    /* =========================================================
       NÚCLEO — anel de poeira em volta de uma estrela tapada
       (como as fotos de telescópio com coronógrafo: disco negro no centro,
       raios de luz em volta e um anel de poeira inclinado em brasa)
       ========================================================= */
    let alvo = ESTADOS.espera, atual = { brilho: .42, giro: .25, raio: 1, cor: [154, 135, 112] };
    const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
    let semente = 7331;
    const rnd = () => ((semente = (semente * 16807) % 2147483647) / 2147483647);
    const gauss = () => (rnd() + rnd() + rnd() - 1.5) / 1.5;

    // poeira do anel: posição no anel (ângulo) + desvio para dentro/fora (mais espalhado para fora)
    const anel = Array.from({ length: 2600 }, () => {
      const d = gauss();
      return { a: rnd() * Math.PI * 2, d: d < 0 ? d * .035 : d * .11, s: .6 + rnd() * 1.4, b: .35 + rnd() * .65 };
    });
    // grão de fundo (o "ruído" avermelhado da imagem)
    const grao = Array.from({ length: 3200 }, () => ({ x: rnd(), y: rnd(), s: .5 + rnd(), b: rnd() }));
    // raios em volta do disco
    const raios = Array.from({ length: 520 }, () => ({ a: rnd() * Math.PI * 2, l: .25 + Math.pow(rnd(), 2.2) * .9, b: .3 + rnd() * .7 }));
    // aglomerados de luz soltos no campo
    const nos = Array.from({ length: 5 }, () => ({ x: .15 + rnd() * .7, y: .55 + rnd() * .4, r: .012 + rnd() * .012 }));

    function desenhar(t) {
      const W = cv.width, H = cv.height, M = Math.min(W, H);
      const k = .05;
      atual.brilho += (alvo.brilho - atual.brilho) * k;
      atual.giro += (alvo.giro - atual.giro) * k;
      atual.raio += (alvo.raio - atual.raio) * k;
      const c2 = hex(alvo.cor); atual.cor = atual.cor.map((v, i) => v + (c2[i] - v) * k);
      const [cr, cg, cb] = atual.cor.map(Math.round);
      const B = atual.brilho;
      const fala = alvo === ESTADOS.falando && !calmo ? Math.max(0, Math.sin(t / 110) * .5 + Math.sin(t / 47) * .5) : 0;
      const respira = calmo ? 0 : Math.sin(t / 1100) * .5 + .5;
      const erro = alvo === ESTADOS.erro;

      // fundo: negro com névoa avermelhada e grão
      cx.fillStyle = "#070302"; cx.fillRect(0, 0, W, H);
      let g = cx.createRadialGradient(W * .5, H * .5, 0, W * .5, H * .5, M * .75);
      g.addColorStop(0, `rgba(${erro ? 140 : 130},${erro ? 18 : 40},12,${.6 * B + .25})`);
      g.addColorStop(1, "rgba(20,5,2,0)");
      cx.fillStyle = g; cx.fillRect(0, 0, W, H);
      for (const p of grao) {
        const v = p.b * (.25 + .5 * B);
        cx.fillStyle = `rgba(${200 + 55 * p.b | 0},${60 + 90 * p.b * p.b | 0},25,${v * .9})`;
        cx.fillRect(p.x * W, p.y * H, p.s * M * .0028, p.s * M * .0028);
      }
      for (const n of nos) {
        g = cx.createRadialGradient(n.x * W, n.y * H, 0, n.x * W, n.y * H, n.r * M);
        g.addColorStop(0, `rgba(255,170,80,${.35 * B})`); g.addColorStop(1, "rgba(255,120,40,0)");
        cx.fillStyle = g; cx.beginPath(); cx.arc(n.x * W, n.y * H, n.r * M, 0, Math.PI * 2); cx.fill();
      }

      // anel de poeira inclinado, com a estrela fora do centro dele
      const X = W * .5, Y = H * .52;
      const rx = M * .40 * atual.raio, ry = M * .25 * atual.raio, inclina = -0.52;
      const ox = M * .03, oy = -M * .05;                                  // centro do anel deslocado da estrela
      if (!calmo) for (const p of anel) p.a += .0009 * (.3 + atual.giro);
      cx.save(); cx.translate(X + ox, Y + oy); cx.rotate(inclina);
      cx.globalCompositeOperation = "lighter";
      for (const p of anel) {
        const lado = .55 + .45 * Math.cos(p.a - 2.6);                     // um lado do anel mais brilhante
        const px = Math.cos(p.a) * rx * (1 + p.d), py = Math.sin(p.a) * ry * (1 + p.d);
        const a = p.b * lado * (.3 + .9 * B) * (1 - Math.min(1, Math.abs(p.d) * 5));
        cx.fillStyle = `rgba(255,${Math.round(150 + 90 * lado * p.b)},${Math.round(90 + 110 * lado * lado)},${a})`;
        const tam = p.s * M * .0032;
        cx.fillRect(px, py, tam, tam);
      }
      cx.restore();

      // raios em volta do disco (luz da estrela vazando pela borda)
      const rd = M * .145;
      cx.save(); cx.translate(X, Y); cx.globalCompositeOperation = "lighter";
      for (const r of raios) {
        const l = rd * (1 + r.l * (.55 + .5 * B + .35 * fala));
        const x1 = Math.cos(r.a) * rd * .96, y1 = Math.sin(r.a) * rd * .96;
        const x2 = Math.cos(r.a) * l, y2 = Math.sin(r.a) * l;
        g = cx.createLinearGradient(x1, y1, x2, y2);
        g.addColorStop(0, `rgba(255,${erro ? 120 : 240},${erro ? 110 : 215},${r.b * (.25 + .6 * B)})`);
        g.addColorStop(1, "rgba(255,180,120,0)");
        cx.strokeStyle = g; cx.lineWidth = M * .0022;
        cx.beginPath(); cx.moveTo(x1, y1); cx.lineTo(x2, y2); cx.stroke();
      }
      cx.globalCompositeOperation = "source-over";

      // disco negro (o "tapa-sol") e a estrela no meio
      cx.fillStyle = "#000"; cx.beginPath();
      for (let i = 0; i <= 64; i++) {                                      // borda levemente irregular
        const a = (i / 64) * Math.PI * 2, rr = rd * (1 + .025 * Math.sin(a * 7) + .015 * Math.sin(a * 13));
        i ? cx.lineTo(Math.cos(a) * rr, Math.sin(a) * rr) : cx.moveTo(Math.cos(a) * rr, Math.sin(a) * rr);
      }
      cx.fill();
      const pulso = .6 + .25 * respira + .6 * fala + (alvo === ESTADOS.ouvindo ? .3 : 0);
      g = cx.createRadialGradient(0, 0, 0, 0, 0, M * .03 * pulso);
      g.addColorStop(0, `rgba(255,255,255,${.6 + .4 * B})`);
      g.addColorStop(.35, `rgba(${cr},${cg},${cb},${.5 * B})`);
      g.addColorStop(1, "rgba(0,0,0,0)");
      cx.fillStyle = g; cx.beginPath(); cx.arc(0, 0, M * .03 * pulso, 0, Math.PI * 2); cx.fill();
      cx.fillStyle = "#fff"; cx.beginPath(); cx.arc(0, 0, M * .009, 0, Math.PI * 2); cx.fill();
      cx.restore();

      // pensando: um ponto percorre o anel (como o detalhe da órbita na foto)
      if (alvo === ESTADOS.pensando && !calmo) {
        const a = t / 500;
        cx.save(); cx.translate(X + ox, Y + oy); cx.rotate(inclina);
        cx.fillStyle = "rgba(255,240,200,.95)";
        cx.beginPath(); cx.arc(Math.cos(a) * rx, Math.sin(a) * ry, M * .006, 0, Math.PI * 2); cx.fill();
        cx.restore();
      }
      requestAnimationFrame(desenhar);
    }

    function ajustar() {                       // nitidez em telas de alta densidade
      const r = cv.getBoundingClientRect(), d = Math.min(2, window.devicePixelRatio || 1);
      const lado = Math.round(Math.max(200, r.width) * d);
      if (lado && cv.width !== lado) { cv.width = lado; cv.height = lado; }
    }
    window.addEventListener("resize", ajustar); ajustar();
    requestAnimationFrame(desenhar);
    return { estado(nome) { alvo = ESTADOS[nome] || ESTADOS.espera; } };
  }
  window.GhostNucleo = { criar, ESTADOS };
})();
