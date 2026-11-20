// Ease callouts in as they scroll into view. Content stays visible without JS or with reduced motion,
// because the hidden starting state only applies once the `js-reveal` class is set here.
(function () {
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  var observer = null;

  function reveal() {
    if (reduceMotion.matches || !("IntersectionObserver" in window)) return;
    document.documentElement.classList.add("js-reveal");
    if (observer) observer.disconnect();
    observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: "0px 0px -5% 0px" });
    document.querySelectorAll(".md-typeset .admonition, .md-typeset details").forEach(function (el) {
      observer.observe(el);
    });
  }

  // Material's instant navigation swaps pages without a reload and emits on document$ each time.
  if (window.document$) {
    window.document$.subscribe(reveal);
  } else {
    document.addEventListener("DOMContentLoaded", reveal);
  }
})();
