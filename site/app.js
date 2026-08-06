/* ═══════════════════════════════════════════════════════════════
   PromoLink Brasil — vitrine
   Consome window.LUMINA_PRODUCTS, exportado pelo bot (export-site).
   ═══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var PRODUCTS = Array.isArray(window.LUMINA_PRODUCTS) ? window.LUMINA_PRODUCTS.slice() : [];
  var FAV_KEY = 'promolink_favs';

  /* ── Marcas ──────────────────────────────────────────────────
     Marcas desenhadas em SVG nas cores oficiais de cada loja para
     identificar a origem da oferta. Sao representacoes proprias,
     nao os arquivos de logo oficiais. */
  var STORES = {
    amazon: {
      label: 'Amazon',
      color: '#FF9900',
      svg: '<svg viewBox="0 0 62 22" role="img" aria-label="Amazon">' +
        '<text x="0" y="14" font-family="Inter,Arial,sans-serif" font-size="14" font-weight="700" fill="currentColor">amazon</text>' +
        '<path d="M2 17.6c5.6 3.4 12.6 3.4 18.2.3" stroke="#FF9900" stroke-width="2.1" fill="none" stroke-linecap="round"/>' +
        '<path d="M19.4 16.2l2.6 1-1.4 2.4z" fill="#FF9900"/></svg>'
    },
    mercadolivre: {
      label: 'Mercado Livre',
      color: '#FFE600',
      svg: '<svg viewBox="0 0 40 22" role="img" aria-label="Mercado Livre">' +
        '<rect x="0" y="2" width="40" height="18" rx="9" fill="#FFE600"/>' +
        '<text x="20" y="15" text-anchor="middle" font-family="Inter,Arial,sans-serif" font-size="10" font-weight="800" fill="#2D3277">ML</text></svg>'
    },
    shopee: {
      label: 'Shopee',
      color: '#EE4D2D',
      svg: '<svg viewBox="0 0 22 22" role="img" aria-label="Shopee">' +
        '<path d="M4 7h14l-1.3 12.2a2 2 0 0 1-2 1.8H7.3a2 2 0 0 1-2-1.8z" fill="#EE4D2D"/>' +
        '<path d="M8 7a3 3 0 0 1 6 0" stroke="#EE4D2D" stroke-width="1.7" fill="none" stroke-linecap="round"/>' +
        '<text x="11" y="17" text-anchor="middle" font-family="Inter,Arial,sans-serif" font-size="8" font-weight="800" fill="#fff">S</text></svg>'
    },
    aliexpress: {
      label: 'AliExpress',
      color: '#FF4747',
      svg: '<svg viewBox="0 0 22 22" role="img" aria-label="AliExpress">' +
        '<circle cx="11" cy="11" r="10" fill="#FF4747"/>' +
        '<text x="11" y="15" text-anchor="middle" font-family="Inter,Arial,sans-serif" font-size="11" font-weight="800" fill="#fff">A</text></svg>'
    },
    manual: {
      label: 'Seleção',
      color: '#E5C77E',
      svg: '<svg viewBox="0 0 22 22" role="img" aria-label="Seleção"><circle cx="11" cy="11" r="10" fill="#E5C77E"/>' +
        '<path d="M6.5 11.2l3 3 6-6.4" stroke="#17130A" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    }
  };

  var CATEGORY_ICONS = {
    'Tecnologia': 'M4 5h16v11H4zM9 20h6M12 16v4',
    'Casa e cozinha': 'M4 10 12 3l8 7M6 10v10h12V10',
    'Eletrodomesticos': 'M6 3h12v18H6zM6 9h12M10 6h.01M10 14h.01',
    'Cama, mesa e banho': 'M3 18v-6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v6M3 14h18M7 10V7h5v3',
    'Ferramentas': 'M14.7 6.3a4 4 0 0 1-5.4 5.4L4 17v3h3l5.3-5.3a4 4 0 0 1 5.4-5.4l-2.5 2.5 1.6 1.6 2.5-2.5',
    'Moda': 'M8 3l4 3 4-3 4 4-3 3v11H7V10L4 7z',
    'Beleza': 'M9 3h6v5a3 3 0 0 1-6 0zM10 13h4v8h-4z',
    'Pets': 'M5 10a2 2 0 1 1 0-4 2 2 0 0 1 0 4zm14 0a2 2 0 1 1 0-4 2 2 0 0 1 0 4zM9 7a2 2 0 1 1 0-4 2 2 0 0 1 0 4zm6 0a2 2 0 1 1 0-4 2 2 0 0 1 0 4zM12 12c3 0 5 2.5 5 5a3 3 0 0 1-3 3h-4a3 3 0 0 1-3-3c0-2.5 2-5 5-5z',
    'Brinquedos': 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM8 11h.01M16 11h.01M9 15c1.8 1.3 4.2 1.3 6 0',
    'Automotivo': 'M5 13l1.6-5h10.8L19 13M4 13h16v5h-3v-2H7v2H4z',
    'Outras ofertas': 'M12 3l2.6 5.6 6.4.8-4.6 4.4 1.1 6.2-5.5-3-5.5 3 1.1-6.2L3 9.4l6.4-.8z'
  };
  var DEFAULT_ICON = CATEGORY_ICONS['Outras ofertas'];

  /* ── Estado ──────────────────────────────────────────────── */
  var state = {
    category: 'all',
    store: 'all',
    search: '',
    sort: 'score',
    minPrice: null,
    maxPrice: null,
    freeShipping: false,
    favsOnly: false
  };

  var favs = loadFavs();

  /* ── Utilitários ─────────────────────────────────────────── */
  function $(id) { return document.getElementById(id); }

  function loadFavs() {
    try { return JSON.parse(localStorage.getItem(FAV_KEY)) || []; }
    catch (e) { return []; }
  }

  function saveFavs() {
    try { localStorage.setItem(FAV_KEY, JSON.stringify(favs)); } catch (e) { /* modo privado */ }
  }

  function money(value, currency) {
    var n = Number(value) || 0;
    if (n <= 0) return 'Ver preço';
    try {
      return n.toLocaleString('pt-BR', { style: 'currency', currency: currency || 'BRL' });
    } catch (e) {
      return 'R$ ' + n.toFixed(2).replace('.', ',');
    }
  }

  function escapeHtml(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function store(source) { return STORES[source] || STORES.manual; }

  function normalize(text) {
    // Remove acentos para a busca casar "sofa" com "sofá"
    return String(text || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  }

  /* ── Navegação lateral ───────────────────────────────────── */
  function buildNav() {
    var catCounts = {};
    var storeCounts = {};

    PRODUCTS.forEach(function (p) {
      var dep = p.department || 'Outras ofertas';
      catCounts[dep] = (catCounts[dep] || 0) + 1;
      storeCounts[p.source] = (storeCounts[p.source] || 0) + 1;
    });

    var cats = Object.keys(catCounts).sort(function (a, b) { return catCounts[b] - catCounts[a]; });
    var catNav = $('categoryNav');
    catNav.innerHTML = navButton('all', 'Todas as ofertas', PRODUCTS.length, DEFAULT_ICON, 'category') +
      cats.map(function (c) {
        return navButton(c, c, catCounts[c], CATEGORY_ICONS[c] || DEFAULT_ICON, 'category');
      }).join('');

    var stores = Object.keys(storeCounts).sort(function (a, b) { return storeCounts[b] - storeCounts[a]; });
    var storeNav = $('storeNav');
    storeNav.innerHTML =
      '<button class="nav-item store-item is-active" data-kind="store" data-value="all">' +
        '<span class="nav-ico">' + iconSvg(DEFAULT_ICON) + '</span>' +
        '<span class="nav-text">Todas as lojas</span>' +
        '<span class="nav-count">' + PRODUCTS.length + '</span>' +
      '</button>' +
      stores.map(function (s) {
        var info = store(s);
        return '<button class="nav-item store-item" data-kind="store" data-value="' + escapeHtml(s) + '">' +
          '<span class="store-logo">' + info.svg + '</span>' +
          '<span class="nav-text">' + escapeHtml(info.label) + '</span>' +
          '<span class="nav-count">' + storeCounts[s] + '</span>' +
        '</button>';
      }).join('');

    [catNav, storeNav].forEach(function (nav) {
      nav.addEventListener('click', function (ev) {
        var btn = ev.target.closest('.nav-item');
        if (!btn) return;
        var kind = btn.dataset.kind;
        state[kind] = btn.dataset.value;
        if (kind === 'category') state.favsOnly = false;
        syncNav();
        render();
        closeSidebar();
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    });
  }

  function iconSvg(path) {
    return '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + path + '"/></svg>';
  }

  function navButton(value, label, count, icon, kind) {
    return '<button class="nav-item" data-kind="' + kind + '" data-value="' + escapeHtml(value) + '">' +
      '<span class="nav-ico">' + iconSvg(icon) + '</span>' +
      '<span class="nav-text">' + escapeHtml(label) + '</span>' +
      '<span class="nav-count">' + count + '</span>' +
    '</button>';
  }

  function syncNav() {
    document.querySelectorAll('.nav-item').forEach(function (btn) {
      var active = state[btn.dataset.kind] === btn.dataset.value;
      btn.classList.toggle('is-active', active);
    });
  }

  /* ── Filtro e ordenação ──────────────────────────────────── */
  function visibleProducts() {
    var term = normalize(state.search).trim();

    var list = PRODUCTS.filter(function (p) {
      if (state.favsOnly && favs.indexOf(p.id) === -1) return false;
      if (state.category !== 'all' && (p.department || 'Outras ofertas') !== state.category) return false;
      if (state.store !== 'all' && p.source !== state.store) return false;
      if (state.freeShipping && !p.freeShipping) return false;

      var price = Number(p.price) || 0;
      if (state.minPrice != null && price < state.minPrice) return false;
      if (state.maxPrice != null && price > state.maxPrice) return false;

      if (term) {
        var haystack = normalize(p.title + ' ' + (p.categoryLabel || '') + ' ' + (p.department || '') + ' ' + store(p.source).label);
        if (haystack.indexOf(term) === -1) return false;
      }
      return true;
    });

    var sorters = {
      score: function (a, b) { return (b.score || 0) - (a.score || 0); },
      // Ranking de mais vendidos: 1 e melhor, e quem nao tem fica no fim
      rank: function (a, b) { return (a.bestsellerRank || 9999) - (b.bestsellerRank || 9999); },
      discount: function (a, b) { return (b.discountPercent || 0) - (a.discountPercent || 0); },
      priceAsc: function (a, b) { return (a.price || 0) - (b.price || 0); },
      priceDesc: function (a, b) { return (b.price || 0) - (a.price || 0); },
      rating: function (a, b) { return (b.rating || 0) - (a.rating || 0); }
    };

    return list.sort(sorters[state.sort] || sorters.score);
  }

  /* ── Card ────────────────────────────────────────────────── */
  function cardHtml(p) {
    var info = store(p.source);
    var isFav = favs.indexOf(p.id) !== -1;
    var discount = Math.round(p.discountPercent || 0);
    var badges = '';

    if (p.bestsellerRank) {
      // O ranking e por categoria, entao o numero sozinho faria varios produtos
      // aparecerem como "#1" ao mesmo tempo. A categoria desfaz a ambiguidade.
      var where = p.bestsellerCategory ? ' em ' + p.bestsellerCategory : '';
      badges += '<span class="badge badge-rank">#' + p.bestsellerRank + escapeHtml(where) + '</span>';
    }
    if (discount >= 5) {
      badges += '<span class="badge badge-off">-' + discount + '%</span>';
    }
    if (p.freeShipping) {
      badges += '<span class="badge badge-ship">FRETE GRÁTIS</span>';
    }

    var priceWas = (p.originalPrice && p.originalPrice > p.price)
      ? '<s class="price-was">' + escapeHtml(money(p.originalPrice, p.currency)) + '</s>' : '';

    var rating = p.rating
      ? '<span class="rating">★ ' + Number(p.rating).toFixed(1).replace('.', ',') + '</span>' : '';

    return '<article class="card" data-id="' + p.id + '">' +
      '<div class="card-media">' +
        '<img src="' + escapeHtml(p.imageUrl) + '" alt="' + escapeHtml(p.title) + '" loading="lazy" decoding="async">' +
        (badges ? '<div class="card-badges">' + badges + '</div>' : '') +
        '<button class="fav' + (isFav ? ' is-on' : '') + '" data-act="fav" type="button" ' +
          'aria-label="' + (isFav ? 'Remover dos favoritos' : 'Adicionar aos favoritos') + '" aria-pressed="' + isFav + '">' +
          '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
          '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>' +
        '</button>' +
      '</div>' +
      '<div class="card-body">' +
        '<div class="card-top">' +
          '<span class="store-chip" style="color:' + info.color + '">' + info.svg + '</span>' +
          rating +
        '</div>' +
        '<h3 class="card-title">' + escapeHtml(p.title) + '</h3>' +
        '<div class="card-price"><span class="price">' + escapeHtml(money(p.price, p.currency)) + '</span>' + priceWas + '</div>' +
        '<div class="card-cta">' +
          '<a class="btn-buy" href="' + escapeHtml(p.affiliateUrl) + '" target="_blank" rel="noopener noreferrer sponsored">' +
            'Ver oferta' +
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>' +
          '</a>' +
          '<button class="btn-more" data-act="details" type="button" aria-label="Ver detalhes">' +
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 8h.01M11 12h1v4h1"/><circle cx="12" cy="12" r="9"/></svg>' +
          '</button>' +
        '</div>' +
      '</div>' +
    '</article>';
  }

  /* ── Render ──────────────────────────────────────────────── */
  function render() {
    var list = visibleProducts();
    var grid = $('grid');

    grid.innerHTML = list.map(cardHtml).join('');
    $('empty').hidden = list.length > 0;
    $('resultCount').textContent = list.length + (list.length === 1 ? ' produto' : ' produtos');

    var title = state.favsOnly ? 'Seus favoritos'
      : state.category === 'all' ? 'Todas as ofertas' : state.category;
    $('catalogTitle').textContent = title;

    var sub = state.store === 'all' ? 'Explore por categoria na barra lateral'
      : 'Filtrando por ' + store(state.store).label;
    $('catalogSubtitle').textContent = sub;

    renderRail();
  }

  function renderRail() {
    // A vitrine de destaque so faz sentido sem filtro ativo
    var neutral = state.category === 'all' && state.store === 'all' &&
      !state.search && !state.favsOnly && state.minPrice == null &&
      state.maxPrice == null && !state.freeShipping;

    var section = $('railSection');
    if (!neutral) { section.hidden = true; return; }

    var ranked = PRODUCTS.filter(function (p) { return p.bestsellerRank; })
      .sort(function (a, b) { return a.bestsellerRank - b.bestsellerRank; }).slice(0, 12);

    var discounted = PRODUCTS.filter(function (p) { return (p.discountPercent || 0) >= 15; })
      .sort(function (a, b) { return b.discountPercent - a.discountPercent; }).slice(0, 12);

    var useDiscount = discounted.length >= 4;
    var picks = useDiscount ? discounted : ranked;

    if (picks.length < 4) { section.hidden = true; return; }

    $('railTitle').textContent = useDiscount ? 'Maiores descontos' : 'Campeões de venda';
    $('railSubtitle').textContent = useDiscount
      ? 'As quedas de preço mais fortes agora'
      : 'Os mais vendidos dos marketplaces';
    $('railGrid').innerHTML = picks.map(cardHtml).join('');
    section.hidden = false;
  }

  function renderStats() {
    var stores = {};
    var cats = {};
    PRODUCTS.forEach(function (p) { stores[p.source] = 1; cats[p.department || 'Outras'] = 1; });

    $('statTotal').textContent = PRODUCTS.length;
    $('statStores').textContent = Object.keys(stores).length;
    $('statCats').textContent = Object.keys(cats).length;

    // O destaque muda conforme o acervo: desconto quando existe, senao nota media
    var best = PRODUCTS.reduce(function (acc, p) {
      return (p.discountPercent || 0) > (acc.discountPercent || 0) ? p : acc;
    }, {});

    if (best.discountPercent >= 5) {
      $('statHighlight').textContent = '-' + Math.round(best.discountPercent) + '%';
      $('statHighlightLabel').textContent = 'Maior desconto';
    } else {
      var rated = PRODUCTS.filter(function (p) { return p.rating; });
      if (rated.length) {
        var avg = rated.reduce(function (s, p) { return s + p.rating; }, 0) / rated.length;
        $('statHighlight').textContent = avg.toFixed(1).replace('.', ',');
        $('statHighlightLabel').textContent = 'Nota média';
      }
    }
  }

  /* ── Drawer ──────────────────────────────────────────────── */
  function openDrawer(product) {
    var info = store(product.source);
    var specs = [];

    if (product.bestsellerRank) {
      specs.push(['Ranking', '#' + product.bestsellerRank + ' mais vendidos' +
        (product.bestsellerCategory ? ' em ' + product.bestsellerCategory : '')]);
    }
    if (product.rating) specs.push(['Avaliação', Number(product.rating).toFixed(1).replace('.', ',') + ' / 5']);
    if (product.soldQuantity) specs.push(['Avaliações', Number(product.soldQuantity).toLocaleString('pt-BR')]);
    if (product.discountPercent >= 1) specs.push(['Desconto', Math.round(product.discountPercent) + '%']);
    if (product.categoryLabel) specs.push(['Categoria', product.categoryLabel]);
    specs.push(['Loja', info.label]);
    specs.push(['Frete grátis', product.freeShipping ? 'Sim' : 'Não informado']);

    var priceWas = (product.originalPrice && product.originalPrice > product.price)
      ? '<s class="price-was">' + escapeHtml(money(product.originalPrice, product.currency)) + '</s>' : '';

    $('drawerContent').innerHTML =
      '<div class="drawer-media"><img src="' + escapeHtml(product.imageUrl) + '" alt="' + escapeHtml(product.title) + '"></div>' +
      '<div class="drawer-body">' +
        '<h3>' + escapeHtml(product.title) + '</h3>' +
        '<div class="drawer-price"><span class="price">' + escapeHtml(money(product.price, product.currency)) + '</span>' + priceWas + '</div>' +
        '<dl class="spec-list">' + specs.map(function (s) {
          return '<div class="spec"><dt>' + escapeHtml(s[0]) + '</dt><dd>' + escapeHtml(s[1]) + '</dd></div>';
        }).join('') + '</dl>' +
        '<a class="btn-buy" href="' + escapeHtml(product.affiliateUrl) + '" target="_blank" rel="noopener noreferrer sponsored">' +
          'Ver oferta na ' + escapeHtml(info.label) +
          '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M5 12h14M12 5l7 7-7 7"/></svg>' +
        '</a>' +
        '<p class="disclaimer">Preço e disponibilidade podem mudar a qualquer momento no site da loja. ' +
        'Este site participa de programas de afiliados e pode receber comissão pelas compras.</p>' +
      '</div>';

    $('drawer').classList.add('is-open');
    $('drawer').setAttribute('aria-hidden', 'false');
    $('sidebarBackdrop').classList.add('is-open');
  }

  function closeDrawer() {
    $('drawer').classList.remove('is-open');
    $('drawer').setAttribute('aria-hidden', 'true');
    if (!$('sidebar').classList.contains('is-open')) $('sidebarBackdrop').classList.remove('is-open');
  }

  /* ── Sidebar mobile ──────────────────────────────────────── */
  function openSidebar() {
    $('sidebar').classList.add('is-open');
    $('sidebarBackdrop').classList.add('is-open');
    $('burger').setAttribute('aria-expanded', 'true');
  }

  function closeSidebar() {
    $('sidebar').classList.remove('is-open');
    $('burger').setAttribute('aria-expanded', 'false');
    if (!$('drawer').classList.contains('is-open')) $('sidebarBackdrop').classList.remove('is-open');
  }

  /* ── Eventos ─────────────────────────────────────────────── */
  function bind() {
    var debounce;
    $('searchInput').addEventListener('input', function (ev) {
      clearTimeout(debounce);
      var value = ev.target.value;
      debounce = setTimeout(function () { state.search = value; render(); }, 180);
    });

    $('sortSelect').addEventListener('change', function (ev) { state.sort = ev.target.value; render(); });

    $('minPrice').addEventListener('input', function (ev) {
      state.minPrice = ev.target.value === '' ? null : Number(ev.target.value);
      render();
    });

    $('maxPrice').addEventListener('input', function (ev) {
      state.maxPrice = ev.target.value === '' ? null : Number(ev.target.value);
      render();
    });

    $('freeShipping').addEventListener('change', function (ev) { state.freeShipping = ev.target.checked; render(); });

    $('clearFilters').addEventListener('click', function () {
      state.category = 'all'; state.store = 'all'; state.search = '';
      state.minPrice = null; state.maxPrice = null; state.freeShipping = false;
      state.favsOnly = false; state.sort = 'score';
      $('searchInput').value = ''; $('minPrice').value = ''; $('maxPrice').value = '';
      $('freeShipping').checked = false; $('sortSelect').value = 'score';
      $('favBtn').classList.remove('is-on');
      $('favBtn').setAttribute('aria-pressed', 'false');
      syncNav(); render();
    });

    $('favBtn').addEventListener('click', function () {
      state.favsOnly = !state.favsOnly;
      this.classList.toggle('is-on', state.favsOnly);
      this.setAttribute('aria-pressed', String(state.favsOnly));
      render();
    });

    // Delegação: cobre o grid principal e o trilho de destaques
    document.addEventListener('click', function (ev) {
      var favBtn = ev.target.closest('[data-act="fav"]');
      var moreBtn = ev.target.closest('[data-act="details"]');
      if (!favBtn && !moreBtn) return;

      var card = ev.target.closest('.card');
      if (!card) return;
      var id = Number(card.dataset.id);
      var product = PRODUCTS.filter(function (p) { return p.id === id; })[0];
      if (!product) return;

      if (favBtn) {
        var at = favs.indexOf(id);
        if (at === -1) favs.push(id); else favs.splice(at, 1);
        saveFavs();
        updateFavCount();
        render();
      } else {
        openDrawer(product);
      }
    });

    $('drawerClose').addEventListener('click', closeDrawer);
    $('burger').addEventListener('click', openSidebar);
    $('sidebarBackdrop').addEventListener('click', function () { closeDrawer(); closeSidebar(); });

    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') { closeDrawer(); closeSidebar(); }
    });
  }

  function updateFavCount() { $('favCount').textContent = favs.length; }

  /* ── Início ──────────────────────────────────────────────── */
  function init() {
    if (!PRODUCTS.length) {
      $('empty').hidden = false;
      $('empty').querySelector('h3').textContent = 'Vitrine sendo atualizada';
      $('empty').querySelector('p').textContent = 'As ofertas são publicadas automaticamente ao longo do dia. Volte em instantes.';
    }
    buildNav();
    syncNav();
    updateFavCount();
    renderStats();
    bind();
    render();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
