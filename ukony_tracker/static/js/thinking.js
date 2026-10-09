// Shared Czech verb cycle. Each card owns and clears both timers.
(function () {
  const VERBS = ['Louskám čísla', 'Šmejdím v evidenci', 'Hrabu se v úkonech', 'Budím databázi',
    'Žmoulám sloupečky', 'Cvakám na kalkulačce', 'Šťourám se v tabulkách', 'Mudruju nad grafem',
    'Vařím statistiku', 'Honím čísla po sloupcích', 'Cuchám řádky', 'Probírám fascikl',
    'Počítám na prstech', 'Cinkám korunama', 'Lustruju razítka', 'Šoupám sloupce',
    'Drbu data', 'Šlehám graf', 'Brouzdám v registru', 'Hledám ztracené kačky',
    'Hladím tabulku', 'Louhuju z dat zlato', 'Ladím kalkulačku', 'Šrotuju'];
  window.Thinking = function (card, verbEl) {
    let interval, swap;
    function stop() {
      clearInterval(interval);
      clearTimeout(swap);
      verbEl.classList.remove('is-swap');
      card.hidden = true;
    }
    function start() {
      stop();
      let last = 'Přemýšlím';
      verbEl.textContent = last;
      card.hidden = false;
      card.classList.remove('is-in');
      void card.offsetWidth;
      card.classList.add('is-in');
      interval = setInterval(function () {
        let next;
        do { next = VERBS[Math.floor(Math.random() * VERBS.length)]; } while (next === last);
        last = next;
        const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (!reduced) verbEl.classList.add('is-swap');
        swap = setTimeout(function () {
          verbEl.textContent = next;
          verbEl.classList.remove('is-swap');
        }, reduced ? 0 : 160);
      }, 1700);
    }
    return {start, stop};
  };
})();
