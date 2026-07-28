// Cliente HTTP do EconoFácil — fala com a API FastAPI do backend.
// Gerencia tokens (access + refresh) e tenta renovar automaticamente no 401.

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";

const ACCESS_KEY = "ef_access";
const REFRESH_KEY = "ef_refresh";

export const tokens = {
  get access() {
    return localStorage.getItem(ACCESS_KEY);
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY);
  },
  set({ access_token, refresh_token }) {
    if (access_token) localStorage.setItem(ACCESS_KEY, access_token);
    if (refresh_token) localStorage.setItem(REFRESH_KEY, refresh_token);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : "Erro na requisição");
    this.status = status;
    this.detail = detail;
  }
}

async function tryRefresh() {
  const refresh_token = tokens.refresh;
  if (!refresh_token) return false;
  const res = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token }),
  });
  if (!res.ok) {
    tokens.clear();
    return false;
  }
  tokens.set(await res.json());
  return true;
}

async function request(path, { method = "GET", body, auth = false, retry = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && tokens.access) headers.Authorization = `Bearer ${tokens.access}`;

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401 && auth && retry && (await tryRefresh())) {
    return request(path, { method, body, auth, retry: false });
  }

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? res.statusText);
  return data;
}

export const api = {
  // Auth
  register: (payload) => request("/auth/register", { method: "POST", body: payload }),
  login: (payload) => request("/auth/login", { method: "POST", body: payload }),
  logout: (refresh_token) => request("/auth/logout", { method: "POST", body: { refresh_token } }),
  forgotPassword: (email) => request("/auth/password/forgot", { method: "POST", body: { email } }),

  // Usuário
  me: () => request("/users/me", { auth: true }),
  updateMe: (payload) => request("/users/me", { method: "PATCH", body: payload, auth: true }),

  // LGPD
  consents: () => request("/lgpd/consents", { auth: true }),
  setConsents: (consents) => request("/lgpd/consents", { method: "PUT", body: { consents }, auth: true }),
  exportData: () => request("/lgpd/export", { auth: true }),
  deleteAccount: () => request("/lgpd/account", { method: "DELETE", auth: true }),

  // Catálogo
  categories: () => request("/catalog/categories"),
  products: (params = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== "" && v !== null)
    ).toString();
    return request(`/catalog/products${q ? `?${q}` : ""}`);
  },
  product: (id) => request(`/catalog/products/${id}`),

  // Carrinho
  cart: () => request("/cart", { auth: true }),
  addItem: (product_id, quantity = 1) =>
    request("/cart/items", { method: "POST", body: { product_id, quantity }, auth: true }),
  setQuantity: (product_id, quantity) =>
    request(`/cart/items/${product_id}`, { method: "PATCH", body: { quantity }, auth: true }),
  removeItem: (product_id) => request(`/cart/items/${product_id}`, { method: "DELETE", auth: true }),
  optimize: () => request("/cart/optimize", { auth: true }),
  checkout: (strategy, payment_method) =>
    request("/cart/checkout", { method: "POST", body: { strategy, payment_method }, auth: true }),

  // Pedidos e pagamentos
  orders: () => request("/orders", { auth: true }),
  order: (id) => request(`/orders/${id}`, { auth: true }),
  payment: (id) => request(`/payments/${id}`, { auth: true }),

  // Noor
  noorStatus: () => request("/noor/status"),
  relatedProducts: (productId, limit = 5) =>
    request(`/noor/recommendations/related/${productId}?limit=${limit}`),
  reorderSuggestions: (limit = 5) =>
    request(`/noor/recommendations/reorder?limit=${limit}`, { auth: true }),

  // Receitas
  recipes: (params = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== "" && v !== null)
    ).toString();
    return request(`/recipes${q ? `?${q}` : ""}`);
  },
  recipe: (id) => request(`/recipes/${id}`),
  addRecipeToCart: (id, servings) =>
    request(`/recipes/${id}/add-to-cart${servings ? `?servings=${servings}` : ""}`, {
      method: "POST",
      auth: true,
    }),

  // Listas de compras
  lists: () => request("/lists", { auth: true }),
  createList: (name) => request("/lists", { method: "POST", body: { name }, auth: true }),
  list: (id) => request(`/lists/${id}`, { auth: true }),
  renameList: (id, name) => request(`/lists/${id}`, { method: "PATCH", body: { name }, auth: true }),
  deleteList: (id) => request(`/lists/${id}`, { method: "DELETE", auth: true }),
  addListItem: (id, product_id, quantity = 1) =>
    request(`/lists/${id}/items`, { method: "POST", body: { product_id, quantity }, auth: true }),
  setListItemQuantity: (id, product_id, quantity) =>
    request(`/lists/${id}/items/${product_id}`, { method: "PATCH", body: { quantity }, auth: true }),
  removeListItem: (id, product_id) =>
    request(`/lists/${id}/items/${product_id}`, { method: "DELETE", auth: true }),
  compareList: (id) => request(`/lists/${id}/compare`, { auth: true }),
  addListToCart: (id) => request(`/lists/${id}/add-to-cart`, { method: "POST", auth: true }),
};

export const brl = (v) =>
  (v ?? 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
