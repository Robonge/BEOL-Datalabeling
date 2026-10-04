// 슬라이드 미리보기(근사 배치). review.html과 slides.html이 같이 쓴다(fill_template이 그 자리에 넣는다).
// 파서가 읽은 좌표(EMU)에 텍스트·표·차트 요약·삽입 그림을 놓는다. 글꼴·색·도형 모양은 원본과 다르다.
// 글자 크기는 컨테이너 너비 기준 단위(cqw)로 잡아 미리보기 크기가 바뀌어도 비율이 유지된다.
var SlidePreview = (function(){
  "use strict";
  function el(tag, cls, text){
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function build(L, imap){
    if (!L || !L.w || !L.h || (!(L.items || []).length && !(L.pics || []).length)) return null;
    imap = imap || {};
    var wPt = L.w / 12700;
    function pct(v, base){ return (v / base * 100).toFixed(3) + "%"; }
    function place(e, b){
      e.style.left = pct(b[0], L.w); e.style.top = pct(b[1], L.h);
      e.style.width = pct(b[2], L.w); e.style.height = pct(b[3], L.h);
      return e;
    }
    function fs(pt){ return (pt / wPt * 100).toFixed(3) + "cqw"; }
    var slide = el("div", "slide");
    slide.setAttribute("style", "aspect-ratio:" + L.w + " / " + L.h);
    slide.setAttribute("role", "img");
    slide.setAttribute("aria-label", "슬라이드 근사 미리보기");
    (L.pics || []).forEach(function(p){
      var url = imap[p.sha];
      if (url){
        var im = el("img", "sp"); im.src = url; im.alt = "슬라이드 그림";
        slide.appendChild(place(im, p.b));
      } else {
        slide.appendChild(place(el("div", "sp-ph", "그림"), p.b));
      }
    });
    (L.items || []).forEach(function(it){
      var e;
      if (it.k === "table"){
        e = el("div", "sb tbl");
        var tb = el("table");
        (it.rows || []).forEach(function(r){
          var tr = el("tr");
          r.forEach(function(cell){ tr.appendChild(el("td", null, cell)); });
          tb.appendChild(tr);
        });
        e.appendChild(tb); e.style.fontSize = fs(9);
      } else {
        e = el("div", "sb " + (it.k === "chart" ? "chart" : "") + (it.ph === "title" || it.ph === "ctrTitle" ? " ttl" : ""), it.t || "");
        e.style.fontSize = fs(it.k === "chart" ? 10 : Math.max(6, (it.sz || 1400) / 100));
      }
      slide.appendChild(place(e, it.b));
    });
    return slide;
  }
  return {build: build};
})();
