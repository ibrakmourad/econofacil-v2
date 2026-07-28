import { Routes, Route, NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { useAuth } from "./context/AuthContext.jsx";
import { useCart } from "./context/CartContext.jsx";

import Home from "./pages/Home.jsx";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import ForgotPassword from "./pages/ForgotPassword.jsx";
import Category from "./pages/Category.jsx";
import Product from "./pages/Product.jsx";
import Cart from "./pages/Cart.jsx";
import Checkout from "./pages/Checkout.jsx";
import OrderConfirmed from "./pages/OrderConfirmed.jsx";
import Orders from "./pages/Orders.jsx";
import Profile from "./pages/Profile.jsx";
import Recipes from "./pages/Recipes.jsx";
import Lists from "./pages/Lists.jsx";

function Tabs() {
  const { count, refresh } = useCart();
  const { user } = useAuth();
  useEffect(() => {
    refresh();
  }, [user, refresh]);
  const tab = ({ isActive }) => (isActive ? "on" : "");
  return (
    <nav className="tabs">
      <NavLink to="/" className={tab} end>
        <span className="ic">🏠</span>Início
      </NavLink>
      <NavLink to="/receitas" className={tab}>
        <span className="ic">🍳</span>Receitas
      </NavLink>
      <NavLink to="/carrinho" className={tab}>
        <span className="ic">🛒</span>
        {count > 0 && <span className="badge">{count}</span>}Carrinho
      </NavLink>
      <NavLink to="/pedidos" className={tab}>
        <span className="ic">🧾</span>Pedidos
      </NavLink>
      <NavLink to="/perfil" className={tab}>
        <span className="ic">👤</span>Perfil
      </NavLink>
    </nav>
  );
}

function Layout() {
  const { pathname } = useLocation();
  // rola para o topo ao trocar de rota
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return (
    <div className="app">
      <Outlet />
      <Tabs />
    </div>
  );
}

function RequireAuth({ children }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="spinner">Carregando…</div>;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/cadastro" element={<Register />} />
      <Route path="/recuperar-senha" element={<ForgotPassword />} />

      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/categoria/:id" element={<Category />} />
        <Route path="/produto/:id" element={<Product />} />
        <Route path="/receitas" element={<Recipes />} />
        <Route path="/listas" element={<RequireAuth><Lists /></RequireAuth>} />
        <Route path="/carrinho" element={<RequireAuth><Cart /></RequireAuth>} />
        <Route path="/checkout" element={<RequireAuth><Checkout /></RequireAuth>} />
        <Route path="/pedido/:id" element={<RequireAuth><OrderConfirmed /></RequireAuth>} />
        <Route path="/pedidos" element={<RequireAuth><Orders /></RequireAuth>} />
        <Route path="/perfil" element={<RequireAuth><Profile /></RequireAuth>} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
