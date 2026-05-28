(function () {
  const fallbackImage = "assets/lumina-prime-hero.png";
  const products = normalizeProducts(window.LUMINA_PRODUCTS || []).filter((product) => hasSiteQuality(product));
  const state = {
    query: "",
    source: "all",
    category: "all",
    subcategory: "all",
    sort: "score",
    minPrice: "",
    maxPrice: "",
    freeShippingOnly: false,
    favorites: new Set(JSON.parse(localStorage.getItem("lumina:favorites") || "[]")),
  };

  const grid = document.getElementById("productGrid");
  const template = document.getElementById("productCardTemplate");
  const emptyState = document.getElementById("emptyState");
  const searchInput = document.getElementById("searchInput");
  const sortSelect = document.getElementById("sortSelect");
  const minPriceInput = document.getElementById("minPriceInput");
  const maxPriceInput = document.getElementById("maxPriceInput");
  const freeShippingOnly = document.getElementById("freeShippingOnly");
  const sourceFilters = document.getElementById("sourceFilters");
  const categoryRail = document.getElementById("categoryRail");
  const categoryDetailPanel = document.getElementById("categoryDetailPanel");
  const resultCount = document.getElementById("resultCount");
  const clearFilters = document.getElementById("clearFilters");
  const favoriteCount = document.getElementById("favoriteCount");
  const drawer = document.getElementById("productDrawer");
  const drawerContent = document.getElementById("drawerContent");
  const drawerBackdrop = document.getElementById("drawerBackdrop");
  const drawerClose = document.getElementById("drawerClose");
  const favoritesButton = document.getElementById("favoritesButton");
  const openBestDeal = document.getElementById("openBestDeal");
  let motionObserver = null;
  let parallaxFrame = 0;
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const CATEGORY_TREE = [
    {
      id: "vehicles",
      label: "Veículos",
      departments: ["Automotivo"],
      terms: ["carro", "moto", "pneu", "bateria", "automotivo"],
      groups: [
        categoryGroup("Carros e Motos", ["Carros", "Motos", "Peças automotivas", "Acessórios internos"]),
        categoryGroup("Manutenção", ["Baterias", "Pneus", "Óleo e fluidos", "Ferramentas automotivas"]),
      ],
    },
    {
      id: "supermarket",
      label: "Supermercado",
      terms: ["mercado", "alimento", "bebida", "limpeza", "higiene"],
      groups: [
        categoryGroup("Alimentos", ["Mercearia", "Bebidas", "Café e cápsulas", "Snacks"]),
        categoryGroup("Casa", ["Limpeza", "Higiene", "Organização", "Descartáveis"]),
      ],
    },
    {
      id: "technology",
      label: "Tecnologia",
      departments: ["Tecnologia"],
      terms: [
        "celular",
        "smartphone",
        "iphone",
        "notebook",
        "monitor",
        "ssd",
        "fone",
        "headset",
        "bluetooth",
        "smartwatch",
        "tablet",
        "teclado",
        "mouse",
        "controle",
        "gamer",
      ],
      groups: [
        categoryGroup("Celulares e Telefones", ["Smartphones", "iPhone", "Acessórios para celulares", "Carregadores", "Capas e películas"]),
        categoryGroup("Informática", ["Notebooks", "Monitores", "SSDs e HDs", "Teclados", "Mouses", "Tablets"]),
        categoryGroup("Câmeras e Acessórios", ["Câmeras", "Filmadoras", "Webcams", "Tripés e suportes"]),
        categoryGroup("Eletrônicos, Áudio e Vídeo", ["Fones de ouvido", "Headsets gamer", "Caixas de som", "Áudio portátil", "Drones"]),
        categoryGroup("Games", ["Controles", "Video games", "Acessórios gamer", "Jogos digitais"]),
        categoryGroup("Televisores", ["Smart TVs", "Projetores", "Suportes para TV", "Streaming"]),
      ],
    },
    {
      id: "home",
      label: "Casa e Móveis",
      departments: ["Casa e cozinha", "Cama, mesa e banho"],
      terms: ["casa", "cozinha", "organizador", "luminaria", "móvel", "moveis", "mesa", "banho"],
      groups: [
        categoryGroup("Cozinha", ["Panelas", "Utensílios", "Organizadores", "Cafeteiras", "Liquidificadores"]),
        categoryGroup("Casa", ["Iluminação", "Organização", "Decoração", "Cama, mesa e banho"]),
        categoryGroup("Móveis", ["Escritório", "Sala", "Quarto", "Área gourmet"]),
      ],
    },
    {
      id: "appliances",
      label: "Eletrodomésticos",
      departments: ["Eletrodomesticos", "Casa e cozinha"],
      terms: ["geladeira", "micro-ondas", "microondas", "fritadeira", "air fryer", "aspirador", "ventilador", "climatizador"],
      groups: [
        categoryGroup("Cozinha premium", ["Air fryer", "Micro-ondas", "Geladeiras", "Fornos", "Cooktops"]),
        categoryGroup("Cuidados da casa", ["Aspiradores", "Máquinas de lavar", "Climatizadores", "Ventiladores"]),
      ],
    },
    {
      id: "sports",
      label: "Esportes e Fitness",
      terms: ["fitness", "academia", "bicicleta", "treino", "esporte", "halter", "esteira"],
      groups: [
        categoryGroup("Treino", ["Academia", "Musculação", "Yoga", "Esteiras", "Bicicletas"]),
        categoryGroup("Esportes", ["Futebol", "Ciclismo", "Camping", "Suplementos"]),
      ],
    },
    {
      id: "tools",
      label: "Ferramentas",
      departments: ["Ferramentas"],
      terms: ["furadeira", "parafusadeira", "ferramenta", "chave", "broca", "dewalt"],
      groups: [
        categoryGroup("Ferramentas elétricas", ["Furadeiras", "Parafusadeiras", "Serras", "Kits profissionais"]),
        categoryGroup("Acessórios", ["Brocas", "Chaves", "Organizadores", "Maletas"]),
      ],
    },
    {
      id: "construction",
      label: "Construção",
      terms: ["construção", "construcao", "obra", "tinta", "cimento", "acabamento"],
      groups: [
        categoryGroup("Obra", ["Materiais", "Acabamento", "Pintura", "Elétrica"]),
        categoryGroup("Casa técnica", ["Hidráulica", "Iluminação técnica", "Segurança", "Medição"]),
      ],
    },
    {
      id: "business",
      label: "Indústria e Comércio",
      terms: ["industrial", "comercial", "loja", "balcão", "balcao", "maquina", "máquina"],
      groups: [
        categoryGroup("Operação", ["Máquinas", "Embalagens", "Expositores", "Balanças"]),
        categoryGroup("Comércio", ["PDV", "Impressoras", "Etiquetas", "Organização"]),
      ],
    },
    {
      id: "office",
      label: "Para seu Negócio",
      terms: ["escritório", "escritorio", "notebook", "impressora", "cadeira", "mesa"],
      groups: [
        categoryGroup("Escritório", ["Cadeiras", "Mesas", "Impressoras", "Monitores"]),
        categoryGroup("Produtividade", ["Notebooks", "Headsets", "Roteadores", "Armazenamento"]),
      ],
    },
    {
      id: "pets",
      label: "Pet Shop",
      departments: ["Pets"],
      terms: ["pet", "cachorro", "gato", "ração", "racao"],
      groups: [
        categoryGroup("Pets", ["Cachorros", "Gatos", "Rações", "Brinquedos", "Higiene"]),
        categoryGroup("Casa pet", ["Camas", "Bebedouros", "Coleiras", "Transporte"]),
      ],
    },
    {
      id: "health",
      label: "Saúde",
      terms: ["saúde", "saude", "medidor", "termometro", "termômetro", "bem-estar"],
      groups: [
        categoryGroup("Bem-estar", ["Medidores", "Massagem", "Cuidados diários", "Ortopedia"]),
        categoryGroup("Rotina", ["Higiene", "Sono", "Saúde bucal", "Farmácia"]),
      ],
    },
    {
      id: "vehicle-accessories",
      label: "Acessórios para Veículos",
      departments: ["Automotivo"],
      terms: ["automotivo", "carro", "moto", "suporte", "som automotivo"],
      groups: [
        categoryGroup("Carro", ["Som automotivo", "Suportes", "Câmeras veiculares", "Organização"]),
        categoryGroup("Moto", ["Capacetes", "Luvas", "Baús", "Peças"]),
      ],
    },
    {
      id: "beauty",
      label: "Beleza e Cuidado Pessoal",
      departments: ["Beleza"],
      terms: ["beleza", "barbeador", "escova secadora", "secador", "perfume", "maquiagem"],
      groups: [
        categoryGroup("Cabelo", ["Escovas secadoras", "Secadores", "Pranchas", "Modeladores"]),
        categoryGroup("Cuidados pessoais", ["Barbeadores", "Perfumes", "Skincare", "Maquiagem"]),
      ],
    },
    {
      id: "fashion",
      label: "Moda",
      departments: ["Moda"],
      terms: ["tênis", "tenis", "mochila", "camiseta", "calça", "calca", "relógio", "relogio"],
      groups: [
        categoryGroup("Acessórios", ["Mochilas", "Relógios", "Bolsas", "Carteiras"]),
        categoryGroup("Vestuário", ["Tênis", "Camisetas", "Calças", "Moda esportiva"]),
      ],
    },
    {
      id: "babies",
      label: "Bebês",
      terms: ["bebê", "bebe", "infantil", "mamadeira", "carrinho"],
      groups: [
        categoryGroup("Rotina do bebê", ["Carrinhos", "Mamadeiras", "Higiene", "Quarto"]),
        categoryGroup("Segurança", ["Cadeirinhas", "Babás eletrônicas", "Portões", "Conforto"]),
      ],
    },
    {
      id: "toys",
      label: "Brinquedos",
      departments: ["Brinquedos"],
      terms: ["brinquedo", "lego", "boneca", "carrinho", "infantil"],
      groups: [
        categoryGroup("Infantil", ["Bonecas", "Carrinhos", "Montar e construir", "Educativos"]),
        categoryGroup("Lazer", ["Games infantis", "Área externa", "Pelúcias", "Colecionáveis"]),
      ],
    },
    {
      id: "real-estate",
      label: "Imóveis",
      terms: ["imóvel", "imovel", "casa", "apartamento", "terreno"],
      groups: [
        categoryGroup("Casa", ["Itens para mudança", "Manutenção", "Organização", "Segurança"]),
        categoryGroup("Ambientes", ["Sala", "Quarto", "Cozinha", "Área externa"]),
      ],
    },
    {
      id: "international",
      label: "Internacional",
      departments: ["Outras ofertas"],
      terms: ["aliexpress", "internacional", "importado"],
      groups: [
        categoryGroup("Importados", ["Eletrônicos", "Gadgets", "Casa inteligente", "Acessórios"]),
        categoryGroup("Ofertas globais", ["Cupons", "Frete internacional", "Novidades", "Tendências"]),
      ],
    },
    {
      id: "sustainable",
      label: "Produtos Sustentáveis",
      terms: ["sustentável", "sustentavel", "solar", "reutilizável", "reutilizavel", "eco"],
      groups: [
        categoryGroup("Casa sustentável", ["Energia solar", "Reutilizáveis", "Economia de água", "Organização"]),
        categoryGroup("Uso diário", ["Garrafas", "Ecobags", "LED", "Produtos duráveis"]),
      ],
    },
    {
      id: "best-sellers",
      label: "Mais vendidos",
      special: "bestSellers",
      groups: [
        categoryGroup("Alta procura", ["Mais vendidos", "Frete grátis", "Maior desconto", "Melhor score"]),
        categoryGroup("Confiança", ["Lojas oficiais", "Vendedores fortes", "Produtos com avaliações", "Ofertas publicadas"]),
      ],
    },
    {
      id: "official-stores",
      label: "Lojas oficiais",
      special: "officialStores",
      groups: [
        categoryGroup("Marcas e lojas", ["Lojas oficiais", "Power sellers", "Alta reputação", "Produtos com imagem"]),
        categoryGroup("Compra segura", ["Frete grátis", "Marketplace oficial", "Melhor score", "Várias vendas"]),
      ],
    },
  ];

  init();

  function init() {
    initMotion();
    renderFilters();
    renderMetrics(products);
    renderProducts();
    bindEvents();
  }

  function bindEvents() {
    searchInput.addEventListener("input", (event) => {
      state.query = event.target.value.trim().toLowerCase();
      renderProducts();
    });

    sortSelect.addEventListener("change", (event) => {
      state.sort = event.target.value;
      renderProducts();
    });

    minPriceInput.addEventListener("input", (event) => {
      state.minPrice = event.target.value;
      renderProducts();
    });

    maxPriceInput.addEventListener("input", (event) => {
      state.maxPrice = event.target.value;
      renderProducts();
    });

    freeShippingOnly.addEventListener("change", (event) => {
      state.freeShippingOnly = event.target.checked;
      renderProducts();
    });

    clearFilters.addEventListener("click", () => {
      state.query = "";
      state.source = "all";
      state.category = "all";
      state.subcategory = "all";
      state.sort = "score";
      state.minPrice = "";
      state.maxPrice = "";
      state.freeShippingOnly = false;
      searchInput.value = "";
      sortSelect.value = "score";
      minPriceInput.value = "";
      maxPriceInput.value = "";
      freeShippingOnly.checked = false;
      renderFilters();
      renderProducts();
    });

    drawerClose.addEventListener("click", closeDrawer);
    drawerBackdrop.addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeDrawer();
    });

    favoritesButton.addEventListener("click", () => {
      state.query = "";
      state.source = "favorites";
      state.category = "all";
      state.subcategory = "all";
      searchInput.value = "";
      renderFilters();
      renderProducts();
      document.getElementById("catalogo").scrollIntoView({ behavior: "smooth" });
    });

    openBestDeal.addEventListener("click", () => {
      const best = sortProducts(products.slice(), "score")[0];
      if (best) openDrawer(best);
    });
  }

  function renderFilters() {
    const sourceCounts = countBy(products, (product) => product.source);
    const sources = ["all", ...unique(products.map((product) => product.source))];
    if (state.favorites.size) sources.push("favorites");
    sourceFilters.innerHTML = "";
    sources.forEach((source) => {
      const button = document.createElement("button");
      button.className = `source-filter${state.source === source ? " active" : ""}`;
      button.type = "button";
      button.textContent = filterLabel(sourceLabel(source), sourceCount(source, sourceCounts));
      button.addEventListener("click", () => {
        state.source = source;
        renderFilters();
        renderProducts();
      });
      sourceFilters.appendChild(button);
    });

    categoryRail.innerHTML = "";
    const categories = [{ id: "all", label: "Todas as categorias" }, ...CATEGORY_TREE];
    categories.forEach((category) => {
      const button = document.createElement("button");
      button.className = `category-button${state.category === category.id ? " active" : ""}`;
      button.type = "button";
      button.innerHTML = `
        <span>${escapeHtml(category.label)}</span>
        <small>${categoryCount(category.id)}</small>
      `;
      button.addEventListener("click", () => {
        state.category = category.id;
        state.subcategory = "all";
        renderFilters();
        renderProducts();
      });
      categoryRail.appendChild(button);
    });
    renderCategoryDetails();
    updateFavoriteCount();
  }

  function renderCategoryDetails() {
    const activeEntry = categoryEntry(state.category);
    const detailEntry = activeEntry || {
      id: "all",
      label: "Categorias em destaque",
      groups: CATEGORY_TREE.slice(0, 6).map((entry) => ({
        title: entry.label,
        items: entry.groups
          .flatMap((group) => group.items)
          .slice(0, 5)
          .map((item) => ({ ...item, categoryId: entry.id })),
      })),
    };
    const groups = detailEntry.groups || [];
    categoryDetailPanel.innerHTML = `
      <div class="detail-panel-heading">
        <div>
          <p class="eyebrow">${activeEntry ? "Subcategorias" : "Navegação detalhada"}</p>
          <h3>${escapeHtml(detailEntry.label)}</h3>
        </div>
        <button class="text-button" type="button" data-category-reset>Ver tudo</button>
      </div>
      <div class="detail-groups">
        ${groups.map((group) => renderDetailGroup(detailEntry, group)).join("")}
      </div>
    `;

    categoryDetailPanel.querySelector("[data-category-reset]").addEventListener("click", () => {
      state.category = activeEntry ? activeEntry.id : "all";
      state.subcategory = "all";
      renderFilters();
      renderProducts();
    });

    categoryDetailPanel.querySelectorAll("[data-subcategory]").forEach((button) => {
      button.addEventListener("click", () => {
        const category = button.getAttribute("data-category") || "all";
        state.category = category;
        state.subcategory = button.getAttribute("data-subcategory") || "all";
        renderFilters();
        renderProducts();
      });
    });
  }

  function renderDetailGroup(entry, group) {
    return `
      <section class="detail-group">
        <h4>${escapeHtml(group.title)}</h4>
        <div>
          ${group.items
            .map((item) => {
              const itemCategory = item.categoryId || entry.id;
              const active = itemCategory === state.category && item.id === state.subcategory;
              return `
                <button
                  class="subcategory-button${active ? " active" : ""}"
                  type="button"
                  data-category="${escapeAttr(itemCategory)}"
                  data-subcategory="${escapeAttr(item.id)}"
                >
                  ${escapeHtml(item.label)}
                </button>
              `;
            })
            .join("")}
        </div>
      </section>
    `;
  }

  function renderMetrics(items) {
    const maxDiscount = Math.max(0, ...items.map((product) => product.discountPercent || 0));
    const freeShipping = items.filter((product) => product.freeShipping).length;
    const sources = unique(items.map((product) => product.source)).length;
    const pricedProducts = items.filter((product) => product.price > 0);
    const averagePrice = average(pricedProducts.map((product) => product.price));
    const averageScore = average(items.map((product) => product.score));
    const topCategory = strongestCategory(items);

    document.getElementById("metricProducts").textContent = items.length;
    document.getElementById("metricDiscount").textContent = `${Math.round(maxDiscount)}%`;
    document.getElementById("metricShipping").textContent = freeShipping;
    document.getElementById("metricSources").textContent = sources;
    document.getElementById("avgPrice").textContent = money(averagePrice);
    document.getElementById("avgScore").textContent = Math.round(averageScore);
    document.getElementById("topCategory").textContent = topCategory || "-";
  }

  function renderProducts() {
    const filtered = filterProducts(products);
    const sorted = sortProducts(filtered, state.sort);
    const groups = groupByDepartment(sorted);
    grid.innerHTML = "";

    sortGroupEntries(groups).forEach(([department, items]) => {
      const section = document.createElement("section");
      section.className = "category-section";
      section.innerHTML = `
        <div class="section-heading">
          <div>
            <p class="eyebrow">${escapeHtml(sectionEyebrow(department))}</p>
            <h3>${escapeHtml(department)}</h3>
          </div>
          <span>${items.length} ${items.length === 1 ? "oferta" : "ofertas"}</span>
        </div>
      `;
      const sectionGrid = document.createElement("div");
      sectionGrid.className = "product-grid";
      items.forEach((product) => sectionGrid.appendChild(renderProductCard(product)));
      section.appendChild(sectionGrid);
      grid.appendChild(section);
    });

    resultCount.textContent = `${sorted.length} ${sorted.length === 1 ? "produto encontrado" : "produtos encontrados"}`;
    emptyState.hidden = sorted.length > 0;
    renderMetrics(filtered);
    updateFavoriteCount();
    refreshMotionTargets();
  }

  function renderProductCard(product) {
    const node = template.content.firstElementChild.cloneNode(true);
    const favoriteButton = node.querySelector(".favorite-toggle");
    const mediaButton = node.querySelector(".product-media");
    const image = document.createElement("img");
    const isFavorite = state.favorites.has(String(product.id));

    favoriteButton.classList.toggle("active", isFavorite);
    favoriteButton.textContent = isFavorite ? "♥" : "♡";
    favoriteButton.addEventListener("click", () => toggleFavorite(product));

    image.src = product.imageUrl || fallbackImage;
    image.alt = product.title;
    image.loading = "lazy";
    image.onerror = () => {
      image.src = fallbackImage;
    };
    mediaButton.appendChild(image);
    mediaButton.setAttribute("aria-label", `Ver detalhes de ${product.title}`);
    mediaButton.addEventListener("click", () => openDrawer(product));

    node.querySelector(".source-pill").textContent = sourceLabel(product.source);
    node.querySelector(".category-chip").textContent = product.department;
    const discount = node.querySelector(".discount-pill");
    discount.textContent = product.discountPercent ? `${Math.round(product.discountPercent)}% off` : shippingLabel(product);
    discount.classList.toggle("is-shipping", !product.discountPercent && product.freeShipping);
    node.querySelector("h3").textContent = product.title;
    node.querySelector(".price-row strong").textContent = priceLabel(product);
    const originalPrice = node.querySelector(".price-row s");
    originalPrice.textContent = product.originalPrice ? money(product.originalPrice, product.currency) : "";
    originalPrice.hidden = !product.originalPrice;
    node.querySelector(".product-stats").innerHTML = buildStats(product);
    node.querySelector(".details-button").addEventListener("click", () => openDrawer(product));
    const buyButton = node.querySelector(".buy-button");
    buyButton.href = product.affiliateUrl;
    buyButton.textContent = "Comprar";
    return node;
  }

  function filterProducts(items) {
    const minPrice = Number(state.minPrice || 0);
    const maxPrice = Number(state.maxPrice || 0);
    return items.filter((product) => {
      if (state.source === "favorites" && !state.favorites.has(String(product.id))) return false;
      if (state.source !== "all" && state.source !== "favorites" && product.source !== state.source) return false;
      if (!productMatchesCategory(product, state.category, state.subcategory)) return false;
      if (state.freeShippingOnly && !product.freeShipping) return false;
      if ((minPrice || maxPrice) && product.price <= 0) return false;
      if (minPrice && product.price < minPrice) return false;
      if (maxPrice && product.price > maxPrice) return false;
      if (!state.query) return true;

      return productSearchText(product).includes(simpleText(state.query));
    });
  }

  function sortProducts(items, sort) {
    const sorted = items.slice();
    const byNumber = (selector, direction = "desc") => {
      sorted.sort((a, b) => {
        const result = Number(selector(a) || 0) - Number(selector(b) || 0);
        return direction === "asc" ? result : -result;
      });
    };

    if (sort === "discount") sorted.sort((a, b) => (b.discountPercent - a.discountPercent) || (qualityScore(b) - qualityScore(a)));
    else if (sort === "priceAsc") {
      sorted.sort((a, b) => {
        const priceA = a.price > 0 ? a.price : Number.MAX_SAFE_INTEGER;
        const priceB = b.price > 0 ? b.price : Number.MAX_SAFE_INTEGER;
        return priceA - priceB || qualityScore(b) - qualityScore(a);
      });
    } else if (sort === "priceDesc") sorted.sort((a, b) => (b.price - a.price) || (qualityScore(b) - qualityScore(a)));
    else byNumber((product) => qualityScore(product));
    return sorted;
  }

  function openDrawer(product) {
    const facts = [
      ["Loja", sourceLabel(product.source)],
      ["Categoria", product.categoryLabel],
      ["Frete", shippingLabel(product)],
      ["Score", String(Math.round(product.score))],
    ];
    const specs = [
      ["ID", product.externalId || "-"],
      ["Area", product.department],
      ["Desconto", product.discountPercent ? `${Math.round(product.discountPercent)}%` : "-"],
      ["Avaliacao", product.rating ? `${product.rating.toFixed(1)}/5` : "-"],
      ["Vendidos", product.soldQuantity ? number(product.soldQuantity) : "-"],
      ["Comissao", product.commissionRate ? `${(product.commissionRate * 100).toFixed(2)}%` : "-"],
    ];

    drawerContent.innerHTML = `
      <div class="drawer-media">
        <img src="${escapeAttr(product.imageUrl || fallbackImage)}" alt="${escapeAttr(product.title)}">
      </div>
      <div class="drawer-body">
        <div class="drawer-topline">
          <span>${escapeHtml(sourceLabel(product.source))}</span>
          <span>${escapeHtml(product.department)}</span>
        </div>
        <h2>${escapeHtml(product.title)}</h2>
        <div class="drawer-price">
          <strong>${priceLabel(product)}</strong>
          ${product.originalPrice ? `<s>${money(product.originalPrice, product.currency)}</s>` : ""}
        </div>
        <div class="detail-facts">
          ${facts.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}
        </div>
        <p>
          Oferta separada pela categoria ${escapeHtml(product.department)}. Confira disponibilidade,
          prazo e condicoes finais diretamente no marketplace antes de comprar.
        </p>
        <dl class="spec-list">
          ${specs.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}
        </dl>
        <a class="buy-button drawer-buy" href="${escapeAttr(product.affiliateUrl)}" target="_blank" rel="noopener noreferrer">
          Comprar no marketplace
        </a>
      </div>
    `;
    drawer.hidden = false;
    drawerBackdrop.hidden = false;
    requestAnimationFrame(() => drawer.classList.add("open"));
    drawer.setAttribute("aria-hidden", "false");
  }

  function closeDrawer() {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    setTimeout(() => {
      drawer.hidden = true;
      drawerBackdrop.hidden = true;
    }, 220);
  }

  function toggleFavorite(product) {
    const key = String(product.id);
    if (state.favorites.has(key)) state.favorites.delete(key);
    else state.favorites.add(key);
    localStorage.setItem("lumina:favorites", JSON.stringify([...state.favorites]));
    renderFilters();
    renderProducts();
  }

  function updateFavoriteCount() {
    favoriteCount.textContent = state.favorites.size;
  }

  function normalizeProducts(items) {
    return items.map((item, index) => {
      const product = {
        id: item.id ?? item.externalId ?? index + 1,
        source: item.source || "marketplace",
        externalId: item.externalId || "",
        title: item.title || "Produto selecionado",
        price: Number(item.price || 0),
        originalPrice: item.originalPrice ? Number(item.originalPrice) : null,
        currency: item.currency || "BRL",
        affiliateUrl: item.affiliateUrl || "#",
        imageUrl: item.imageUrl || "",
        category: item.category || "geral",
        categoryLabel: item.categoryLabel || "",
        department: item.department || "",
        score: Number(item.score || 0),
        rating: item.rating ? Number(item.rating) : null,
        soldQuantity: numberOrNull(item.soldQuantity),
        freeShipping: Boolean(item.freeShipping),
        discountPercent: Number(item.discountPercent || 0),
        commissionRate: item.commissionRate ? Number(item.commissionRate) : null,
        offerType: item.offerType || null,
        periodEndTime: item.periodEndTime || null,
        sellerCompletedTransactions: numberOrNull(item.sellerCompletedTransactions),
        sellerPowerStatus: item.sellerPowerStatus || "",
        sellerLevel: item.sellerLevel || "",
        officialStoreId: item.officialStoreId || null,
        officialStoreName: item.officialStoreName || "",
      };
      product.categoryLabel = product.categoryLabel || readableCategory(product);
      product.department = product.department || classifyDepartment(product);
      return product;
    });
  }

  function buildStats(product) {
    const stats = [];
    if (product.freeShipping) stats.push("Frete gratis");
    if (product.discountPercent) stats.push(`${Math.round(product.discountPercent)}% off`);
    if (product.rating) stats.push(`${product.rating.toFixed(1)}/5`);
    if (product.soldQuantity) stats.push(`${number(product.soldQuantity)} vendidos`);
    if (product.officialStoreName) stats.push("Loja oficial");
    else if (product.sellerPowerStatus) stats.push("Vendedor forte");
    else if (product.sellerCompletedTransactions) stats.push(`${number(product.sellerCompletedTransactions)} vendas da loja`);
    stats.push(`Score ${Math.round(product.score)}`);
    return stats.map((stat) => `<span>${escapeHtml(stat)}</span>`).join("");
  }

  function groupByDepartment(items) {
    const groups = new Map();
    items.forEach((product) => {
      const group = product.department || "Outras ofertas";
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(product);
    });
    return groups;
  }

  function sortGroupEntries(groups) {
    return [...groups.entries()].sort((a, b) => {
      const order = categoryOrder(a[0]) - categoryOrder(b[0]);
      if (order !== 0) return order;
      return sumScore(b[1]) - sumScore(a[1]);
    });
  }

  function sortDepartments(departments) {
    return departments.slice().sort((a, b) => categoryOrder(a) - categoryOrder(b) || a.localeCompare(b, "pt-BR"));
  }

  function categoryOrder(category) {
    const order = [
      "Tecnologia",
      "Casa e cozinha",
      "Eletrodomesticos",
      "Cama, mesa e banho",
      "Ferramentas",
      "Moda",
      "Beleza",
      "Pets",
      "Brinquedos",
      "Automotivo",
      "Outras ofertas",
    ];
    const index = order.indexOf(category);
    return index === -1 ? 99 : index;
  }

  function sectionEyebrow(department) {
    const labels = {
      Tecnologia: "Eletronicos e acessorios",
      "Casa e cozinha": "Utilidades para rotina",
      Eletrodomesticos: "Equipamentos para casa",
      "Cama, mesa e banho": "Conforto e organizacao",
      Ferramentas: "Manutencao e reparos",
      Moda: "Uso pessoal",
      Beleza: "Cuidados pessoais",
      Pets: "Produtos para pets",
      Brinquedos: "Infantil e lazer",
      Automotivo: "Carro e moto",
      "Outras ofertas": "Mais oportunidades",
    };
    return labels[department] || "Ofertas selecionadas";
  }

  function classifyDepartment(product) {
    const haystack = `${product.title} ${product.categoryLabel} ${product.category}`.toLowerCase();
    const groups = [
      ["Tecnologia", ["celular", "smartphone", "iphone", "notebook", "monitor", "ssd", "fone", "headset", "bluetooth", "smartwatch", "tablet", "teclado", "mouse", "controle", "xbox", "playstation", "gamer", "caixa de som"]],
      ["Casa e cozinha", ["casa", "cozinha", "air fryer", "panela", "liquidificador", "cafeteira", "utensilio", "utensilio", "jogo de panelas", "organizador", "luminaria"]],
      ["Eletrodomesticos", ["geladeira", "micro-ondas", "microondas", "maquina de lavar", "aspirador", "ventilador", "climatizador", "fritadeira"]],
      ["Cama, mesa e banho", ["cama", "mesa", "banho", "toalha", "jogo de cama", "lencol"]],
      ["Ferramentas", ["furadeira", "parafusadeira", "ferramenta", "chave", "broca"]],
      ["Moda", ["tenis", "mochila", "camiseta", "calca", "relogio"]],
      ["Beleza", ["beleza", "barbeador", "escova secadora", "secador", "perfume", "maquiagem"]],
      ["Pets", ["pet", "cachorro", "gato", "racao"]],
      ["Brinquedos", ["brinquedo", "lego", "boneca", "carrinho"]],
      ["Automotivo", ["carro", "moto", "automotivo", "pneu", "bateria"]],
    ];
    const match = groups.find(([, terms]) => terms.some((term) => haystack.includes(term)));
    return match ? match[0] : "Outras ofertas";
  }

  function readableCategory(product) {
    const category = String(product.category || "").trim();
    if (!category || /^ML[A-Z]\d+/i.test(category)) return classifyDepartment(product);
    return titleCase(category.replaceAll("_", " ").replaceAll("-", " "));
  }

  function initMotion() {
    if (prefersReducedMotion.matches) return;
    document.documentElement.classList.add("motion-ready");
    motionObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          motionObserver.unobserve(entry.target);
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.12 }
    );
    window.addEventListener("scroll", requestParallax, { passive: true });
    window.addEventListener("resize", requestParallax, { passive: true });
    updateParallax();
  }

  function refreshMotionTargets() {
    if (prefersReducedMotion.matches) return;
    const targets = document.querySelectorAll(".metrics-band div, .category-detail-panel, .side-panel, .category-section, .product-card");
    targets.forEach((target, index) => {
      if (target.dataset.motionBound) return;
      target.dataset.motionBound = "true";
      target.style.transitionDelay = `${Math.min((index % 10) * 42, 320)}ms`;
      if (motionObserver) motionObserver.observe(target);
      else target.classList.add("is-visible");
    });
  }

  function requestParallax() {
    if (parallaxFrame) return;
    parallaxFrame = requestAnimationFrame(updateParallax);
  }

  function updateParallax() {
    const scrollY = window.scrollY || 0;
    const heroShift = Math.max(-34, Math.min(34, scrollY * -0.08));
    const sidebarShift = Math.max(-24, Math.min(42, scrollY * 0.035));
    document.documentElement.style.setProperty("--hero-shift", `${heroShift}px`);
    document.documentElement.style.setProperty("--sidebar-shift", `${sidebarShift}px`);
    parallaxFrame = 0;
  }

  function categoryGroup(title, labels) {
    return {
      title,
      items: labels.map((label) => ({
        id: slugify(`${title}-${label}`),
        label,
        terms: categoryTerms(label),
      })),
    };
  }

  function categoryTerms(label) {
    const text = simpleText(label);
    const terms = new Set([text]);
    text.split(" ").filter((part) => part.length > 3).forEach((part) => terms.add(part));
    return [...terms];
  }

  function categoryEntry(id) {
    return CATEGORY_TREE.find((entry) => entry.id === id) || null;
  }

  function findSubcategory(entry, id) {
    return (entry.groups || []).flatMap((group) => group.items).find((item) => item.id === id) || null;
  }

  function productMatchesCategory(product, categoryId, subcategoryId = "all") {
    if (categoryId === "all") return true;
    const entry = categoryEntry(categoryId);
    if (!entry) return true;

    if (entry.special === "bestSellers") {
      return product.soldQuantity >= 5 || product.sellerCompletedTransactions >= 25 || qualityScore(product) >= 45;
    }
    if (entry.special === "officialStores") {
      return Boolean(product.officialStoreId || product.officialStoreName || product.sellerPowerStatus || product.sellerLevel);
    }

    const productText = productSearchText(product);
    const matchesParent =
      (entry.departments || []).includes(product.department) ||
      (entry.terms || []).some((term) => productText.includes(simpleText(term)));
    if (!matchesParent) return false;
    if (subcategoryId === "all") return true;

    const subcategory = findSubcategory(entry, subcategoryId);
    if (!subcategory) return true;
    return subcategory.terms.some((term) => productText.includes(simpleText(term)));
  }

  function hasSiteQuality(product) {
    if (!String(product.imageUrl || "").trim()) return false;
    if (product.soldQuantity !== null && product.soldQuantity < 5) return false;
    if (product.sellerCompletedTransactions !== null && product.sellerCompletedTransactions < 25) return false;
    return true;
  }

  function qualityScore(product) {
    let score = Number(product.score || 0);
    if (product.soldQuantity) score += Math.min(Math.log10(product.soldQuantity + 1) * 8, 22);
    if (product.sellerCompletedTransactions) score += Math.min(Math.log10(product.sellerCompletedTransactions + 1) * 7, 22);
    if (product.sellerPowerStatus) score += 8;
    if (product.officialStoreId || product.officialStoreName) score += 8;
    if (product.imageUrl) score += 4;
    return score;
  }

  function productSearchText(product) {
    return simpleText([
      product.title,
      product.category,
      product.categoryLabel,
      product.department,
      product.source,
      sourceLabel(product.source),
      product.externalId,
      product.officialStoreName,
      product.sellerLevel,
      product.sellerPowerStatus,
    ].join(" "));
  }

  function sourceLabel(source) {
    const labels = {
      all: "Todos",
      aliexpress: "AliExpress",
      amazon: "Amazon",
      favorites: "Favoritos",
      manual: "Manual",
      mercadolivre: "Mercado Livre",
      shopee: "Shopee",
      marketplace: "Marketplace",
    };
    return labels[source] || source;
  }

  function money(value, currency = "BRL") {
    return new Intl.NumberFormat("pt-BR", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(Number(value || 0));
  }

  function priceLabel(product) {
    if (!product.price || product.price <= 0) return "Conferir preco";
    return money(product.price, product.currency);
  }

  function shippingLabel(product) {
    return product.freeShipping ? "Frete gratis" : "Frete no marketplace";
  }

  function number(value) {
    return new Intl.NumberFormat("pt-BR").format(Number(value || 0));
  }

  function titleCase(value) {
    return String(value || "")
      .split(" ")
      .filter(Boolean)
      .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1).toLowerCase())
      .join(" ");
  }

  function unique(items) {
    return [...new Set(items.filter(Boolean))];
  }

  function average(items) {
    const values = items.filter((item) => Number.isFinite(item));
    if (!values.length) return 0;
    return values.reduce((sum, value) => sum + value, 0) / values.length;
  }

  function strongestCategory(items) {
    const counts = new Map();
    items.forEach((product) => {
      counts.set(product.department, (counts.get(product.department) || 0) + qualityScore(product));
    });
    return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || "";
  }

  function countBy(items, selector) {
    const counts = new Map();
    items.forEach((item) => {
      const key = selector(item);
      counts.set(key, (counts.get(key) || 0) + 1);
    });
    return counts;
  }

  function sourceCount(source, counts) {
    if (source === "all") return products.length;
    if (source === "favorites") return products.filter((product) => state.favorites.has(String(product.id))).length;
    return counts.get(source) || 0;
  }

  function categoryCount(categoryId) {
    if (categoryId === "all") return products.length;
    return products.filter((product) => productMatchesCategory(product, categoryId)).length;
  }

  function filterLabel(label, count) {
    return `${label} (${count})`;
  }

  function sumScore(items) {
    return items.reduce((sum, product) => sum + qualityScore(product), 0);
  }

  function numberOrNull(value) {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function simpleText(value) {
    return String(value || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();
  }

  function slugify(value) {
    return simpleText(value)
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replaceAll("`", "&#096;");
  }
})();
