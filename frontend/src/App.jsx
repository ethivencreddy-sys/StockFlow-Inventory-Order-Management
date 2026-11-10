import { useCallback, useEffect, useMemo, useState } from 'react'
import './App.css'
const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8022'

const money = (value) =>
  `₹${Number(value || 0).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`

async function apiRequest(path, options = {}) {
  const token = localStorage.getItem('access_token')

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })

  const text = await response.text()
  let data = null

  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }

  if (!response.ok) {
    throw new Error(
      typeof data?.detail === 'string'
        ? data.detail
        : typeof data === 'string' && data
          ? data
          : `Request failed (${response.status})`,
    )
  }

  return data
}

function asList(result) {
  if (Array.isArray(result)) return result
  if (Array.isArray(result?.items)) return result.items
  if (Array.isArray(result?.data)) return result.data
  return []
}

function productName(product) {
  return product?.name || product?.title || `Product #${product?.id ?? '?'}`
}

function productPrice(product) {
  const price = product?.price ?? product?.unit_price
  return price == null ? null : Number(price)
}

function App() {
  const [activeTab, setActiveTab] = useState('login')
  const [page, setPage] = useState('dashboard')
  const [user, setUser] = useState(null)
  const [products, setProducts] = useState([])
  const [inventory, setInventory] = useState([])
  const [orders, setOrders] = useState([])
  const [cart, setCart] = useState([])
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [dataLoading, setDataLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [showProductForm, setShowProductForm] = useState(false)

  const [productForm, setProductForm] = useState({
    name: '',
    category: '',
    price: '',
    description: '',
  })

  const [busyProductId, setBusyProductId] = useState(null)
  const [busyCartId, setBusyCartId] = useState(null)

  const [stockAdjustment, setStockAdjustment] = useState({
    product_id: '',
    change_quantity: '',
    reason: '',
  })

  const [stockLoading, setStockLoading] = useState(false)
  const [transactions, setTransactions] = useState([])
  const [selectedTransactionProduct, setSelectedTransactionProduct] =
    useState(null)
  const [transactionLoading, setTransactionLoading] = useState(false)
  const [checkoutLoading, setCheckoutLoading] = useState(false)

  const [shippingAddress, setShippingAddress] = useState(
    'Anantapur, Andhra Pradesh, India',
  )

  const userRole = String(user?.role || '').toLowerCase()

  const isAdmin = ['administrator', 'admin'].includes(userRole)

  const canManageInventory = [
    'administrator',
    'admin',
    'inventory_manager',
  ].includes(userRole)

  const loadWorkspace = useCallback(async () => {
    const token = localStorage.getItem('access_token')

    if (!token) {
      setUser(null)
      return
    }

    try {
      const currentUser = await apiRequest('/auth/me')
      setUser(currentUser)
    } catch {
      localStorage.removeItem('access_token')
      setUser(null)
      setMessage('Your session expired. Please sign in again.')
      return
    }

    setDataLoading(true)

    const [productResult, inventoryResult, orderResult, cartResult] =
      await Promise.allSettled([
        apiRequest('/products'),
        apiRequest('/inventory'),
        apiRequest('/orders'),
        apiRequest('/cart'),
      ])

    if (productResult.status === 'fulfilled') {
      setProducts(asList(productResult.value))
    } else {
      setMessage(`Products could not be loaded: ${productResult.reason.message}`)
    }

    if (inventoryResult.status === 'fulfilled') {
      setInventory(asList(inventoryResult.value))
    }

    if (orderResult.status === 'fulfilled') {
      setOrders(asList(orderResult.value))
    }

    if (cartResult.status === 'fulfilled') {
      setCart(asList(cartResult.value))
    }

    setDataLoading(false)
  }, [])

  useEffect(() => {
    if (localStorage.getItem('access_token')) {
      loadWorkspace()
    }
  }, [loadWorkspace])

  async function handleAuth(event) {
    event.preventDefault()
    setMessage('')
    setLoading(true)

    try {
      const endpoint =
        activeTab === 'login' ? '/auth/login' : '/auth/register'

      const payload =
        activeTab === 'login'
          ? { email, password }
          : { username: name, email, password }

      const result = await apiRequest(endpoint, {
        method: 'POST',
        body: JSON.stringify(payload),
      })

      if (activeTab === 'register') {
        setMessage('Registration successful. Please sign in.')
        setActiveTab('login')
        setPassword('')
        return
      }

      const token =
        result?.access_token || result?.accessToken || result?.token

      if (!token) {
        throw new Error('Login succeeded but no access token was returned.')
      }

      localStorage.setItem('access_token', token)
      await loadWorkspace()
      setPage('dashboard')
      setMessage('')
    } catch (error) {
      setMessage(error.message || 'Authentication failed.')
    } finally {
      setLoading(false)
    }
  }

  function logout() {
    localStorage.removeItem('access_token')
    setUser(null)
    setProducts([])
    setInventory([])
    setOrders([])
    setCart([])
    setPage('dashboard')
    setMessage('')
    setPassword('')
  }

  async function refreshProducts() {
    try {
      setDataLoading(true)
      setProducts(asList(await apiRequest('/products')))
      setMessage('Products refreshed.')
    } catch (error) {
      setMessage(`Products: ${error.message}`)
    } finally {
      setDataLoading(false)
    }
  }
  async function adjustStock(event) {
    event.preventDefault()

    if (!canManageInventory) {
      setMessage('You do not have permission to adjust stock.')
      return
    }

    const productId = Number(stockAdjustment.product_id)
    const changeQuantity = Number(stockAdjustment.change_quantity)
    const reason = stockAdjustment.reason.trim()

    if (!productId || !Number.isInteger(productId)) {
      setMessage('Please select a valid product.')
      return
    }

    if (!Number.isInteger(changeQuantity) || changeQuantity === 0) {
      setMessage('Stock change must be a non-zero whole number.')
      return
    }

    if (reason.length < 3) {
      setMessage('Please enter a reason of at least 3 characters.')
      return
    }

    setStockLoading(true)
    setMessage('')

    try {
      await apiRequest(`/inventory/${productId}/stock`, {
        method: 'PATCH',
        body: JSON.stringify({
          change_quantity: changeQuantity,
          reason,
        }),
      })

      setStockAdjustment({
        product_id: '',
        change_quantity: '',
        reason: '',
      })

      const result = await apiRequest('/inventory')
      setInventory(asList(result))
      setMessage('Stock adjusted successfully.')
    } catch (error) {
      setMessage(`Stock adjustment failed: ${error.message}`)
    } finally {
      setStockLoading(false)
    }
  }

  async function loadTransactions(productId) {
    setSelectedTransactionProduct(productId)
    setTransactionLoading(true)
    setTransactions([])
    setMessage('')

    try {
      const result = await apiRequest(
        `/inventory/${productId}/transactions`,
      )
      setTransactions(asList(result))
    } catch (error) {
      setMessage(`Could not load transaction history: ${error.message}`)
    } finally {
      setTransactionLoading(false)
    }
  }

  async function createProduct(event) {
    event.preventDefault()
    setMessage('')

    if (!isAdmin) {
      setMessage('Only administrators can create products.')
      return
    }

    const price = Number(productForm.price)

    if (!productForm.name.trim() || !Number.isFinite(price) || price < 0) {
      setMessage('Enter a product name and a valid non-negative price.')
      return
    }

    setLoading(true)

    try {
      const created = await apiRequest('/products', {
        method: 'POST',
        body: JSON.stringify({
          name: productForm.name.trim(),
          category: productForm.category.trim() || 'General',
          description: productForm.description.trim(),
          price,
        }),
      })

      setProductForm({
        name: '',
        category: '',
        price: '',
        description: '',
      })

      setShowProductForm(false)
      await refreshProducts()
      setMessage(`Product "${productName(created)}" created successfully.`)
    } catch (error) {
      setMessage(
        `Could not create product: ${error.message}. Check the Product Service POST /products schema.`,
      )
    } finally {
      setLoading(false)
    }
  }

  async function addToCart(product) {
    if (!product?.id) {
      setMessage('This product has no valid product ID.')
      return
    }

    setBusyProductId(product.id)
    setMessage('')

    try {
      await apiRequest('/cart/items', {
        method: 'POST',
        body: JSON.stringify({
          product_id: product.id,
          quantity: 1,
        }),
      })

      const result = await apiRequest('/cart')
      setCart(asList(result))
      setMessage(`${productName(product)} added to cart.`)
    } catch (error) {
      setMessage(
        `Could not add product to cart: ${error.message}. Check the Cart Service POST endpoint and request schema.`,
      )
    } finally {
      setBusyProductId(null)
    }
  }

  async function updateCartQuantity(item, newQuantity) {
    if (!item?.id) {
      setMessage('This cart item has no ID for updating its quantity.')
      return
    }

    if (newQuantity < 1) {
      await removeFromCart(item)
      return
    }

    setBusyCartId(item.id)
    setMessage('')

    try {
      await apiRequest(`/cart/items/${item.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ quantity: newQuantity }),
      })

      setCart(asList(await apiRequest('/cart')))
    } catch (error) {
      setMessage(
        `Could not update quantity: ${error.message}. Check the Cart Service update endpoint.`,
      )
    } finally {
      setBusyCartId(null)
    }
  }

  async function removeFromCart(item) {
    if (!item?.id) {
      setMessage('This cart item has no ID for removal.')
      return
    }

    setBusyCartId(item.id)
    setMessage('')

    try {
      await apiRequest(`/cart/items/${item.id}`, { method: 'DELETE' })
      setCart(asList(await apiRequest('/cart')))
      setMessage('Item removed from cart.')
    } catch (error) {
      setMessage(
        `Could not remove item: ${error.message}. Check the Cart Service delete endpoint.`,
      )
    } finally {
      setBusyCartId(null)
    }
  }

  const filteredProducts = products.filter((product) => {
    const term = search.toLowerCase()

    return (
      productName(product).toLowerCase().includes(term) ||
      String(product.category || '').toLowerCase().includes(term)
    )
  })

  const cartRows = useMemo(
    () =>
      cart.map((item) => {
        const product = products.find(
          (p) => Number(p.id) === Number(item.product_id),
        )

        const price =
          item.unit_price != null
            ? Number(item.unit_price)
            : item.price != null
              ? Number(item.price)
              : productPrice(product)

        const quantity = Number(item.quantity ?? 1)

        return {
          ...item,
          displayName:
            productName(product) !== 'Product #?' && product
              ? productName(product)
              : item.product_name || item.name || `Product #${item.product_id ?? '?'}`,
          displayPrice: price,
          displayQuantity: quantity,
          subtotal:
            price == null || !Number.isFinite(price)
              ? null
              : price * quantity,
        }
      }),
    [cart, products],
  )

  const cartTotal = cartRows.reduce(
    (sum, item) => sum + (item.subtotal ?? 0),
    0,
  )

  const cartHasUnknownPrice = cartRows.some(
    (item) => item.subtotal == null,
  )

  async function checkout() {
    if (!cartRows.length) {
      setMessage('Your cart is empty.')
      return
    }

    if (cartHasUnknownPrice) {
      setMessage(
        'Some cart items have no known price. Refresh the products and check the cart API before checkout.',
      )
      return
    }

    setCheckoutLoading(true)
    setMessage('')

    try {
      const orderItems = cartRows.map((item) => ({
        product_id: Number(item.product_id),
        quantity: Number(item.displayQuantity),
        unit_price: Number(item.displayPrice),
      }))

      const order = await apiRequest('/orders', {
        method: 'POST',
        body: JSON.stringify({
          shipping_address: shippingAddress,
          items: orderItems,
        }),
      })

      const removeResults = await Promise.allSettled(
        cartRows.map((item) =>
          apiRequest(`/cart/items/${item.id}`, {
            method: 'DELETE',
          }),
        ),
      )

      const failedRemovals = removeResults.filter(
        (result) => result.status === 'rejected',
      )

      await loadWorkspace()
      setPage('orders')

      if (failedRemovals.length > 0) {
        setMessage(
          `Order #${order.id} created successfully, but some cart items could not be removed. Please open Cart and remove them manually.`,
        )
      } else {
        setMessage(
          `Order #${order.id} created successfully for ${money(order.total_amount)}. Your cart is now empty. Payment is handled separately.`,
        )
      }
    } catch (error) {
      setMessage(`Checkout failed: ${error.message}`)
    } finally {
      setCheckoutLoading(false)
    }
  }
  if (!user) {
    return (
      <main className="app-shell">
        <section className="welcome-panel">
          <div className="brand">
            <span className="brand-icon">SF</span>
            <span>StockFlow</span>
          </div>

          <div className="welcome-content">
            <span className="eyebrow">INVENTORY & ORDER MANAGEMENT</span>
            <h1>Everything in stock. Every order in control.</h1>
            <p>
              Manage products, monitor inventory, organize orders, and keep
              your operations moving from one simple workspace.
            </p>
            <div className="feature-list">
              <div><span>✓</span> Real-time inventory management</div>
              <div><span>✓</span> Streamlined order tracking</div>
              <div><span>✓</span> Secure account access</div>
            </div>
          </div>

          <p className="welcome-footer">One workspace. Better operations.</p>
        </section>

        <section className="auth-panel">
          <div className="auth-card">
            <p className="form-eyebrow">WELCOME TO STOCKFLOW</p>
            <h2>
              {activeTab === 'login'
                ? 'Welcome back'
                : 'Create your account'}
            </h2>
            <p className="form-description">
              {activeTab === 'login'
                ? 'Enter your details to access your workspace.'
                : 'Register to get started with your workspace.'}
            </p>

            <div className="auth-tabs">
              <button
                type="button"
                className={activeTab === 'login' ? 'active' : ''}
                onClick={() => {
                  setActiveTab('login')
                  setMessage('')
                }}
              >
                Sign in
              </button>
              <button
                type="button"
                className={activeTab === 'register' ? 'active' : ''}
                onClick={() => {
                  setActiveTab('register')
                  setMessage('')
                }}
              >
                Create account
              </button>
            </div>

            <form onSubmit={handleAuth}>
              {activeTab === 'register' && (
                <label>
                  Username
                  <input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="Choose a username"
                    required
                  />
                </label>
              )}

              <label>
                Email address
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                  autoComplete="email"
                  required
                />
              </label>

              <label>
                Password
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Enter your password"
                  autoComplete={
                    activeTab === 'login'
                      ? 'current-password'
                      : 'new-password'
                  }
                  required
                />
              </label>

              <button className="submit-button" disabled={loading}>
                {loading
                  ? 'Please wait...'
                  : activeTab === 'login'
                    ? 'Sign in to workspace →'
                    : 'Create account →'}
              </button>
            </form>

            {message && <p className="feedback error">{message}</p>}

            <p className="security-note">
              Your workspace is protected by account authentication.
            </p>
          </div>
        </section>
      </main>
    )
  }

  const navigation = [
    { id: 'dashboard', label: 'Overview', icon: '▦' },
    { id: 'products', label: 'Products', icon: '□' },
    { id: 'inventory', label: 'Inventory', icon: '▤' },
    { id: 'cart', label: 'My Cart', icon: '🛒' },
    { id: 'orders', label: 'Orders', icon: '↗' },
  ]

  return (
    <div className="workspace">
      <aside className="sidebar">
        <div className="brand sidebar-brand">
          <span className="brand-icon">SF</span>
          <span>StockFlow</span>
        </div>

        <p className="nav-heading">WORKSPACE</p>

        <nav className="sidebar-nav">
          {navigation.map((item) => (
            <button
              key={item.id}
              className={
                page === item.id ? 'nav-item selected' : 'nav-item'
              }
              onClick={() => {
                setPage(item.id)
                setMessage('')
              }}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}

              {item.id === 'cart' && cart.length > 0 && (
                <span className="cart-badge">{cart.length}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="user-avatar">
            {(user.username || user.email || 'U')
              .charAt(0)
              .toUpperCase()}
          </div>

          <div className="user-info">
            <strong>{user.username || user.email}</strong>
            <span>{user.role || 'customer'}</span>
          </div>

          <button
            className="logout-button"
            onClick={logout}
            title="Log out"
          >
            ↪
          </button>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div>
            <span className="topbar-label">STOCKFLOW WORKSPACE</span>
            <h1>
              {navigation.find((item) => item.id === page)?.label ||
                'Overview'}
            </h1>
          </div>

          <div className="topbar-user">
            <span className="status-dot" />
            <span>{user.username || user.email}</span>
          </div>
        </header>

        <section className="content-area">
          {message && (
            <div className="dashboard-message">
              {message}
              <button onClick={() => setMessage('')}>×</button>
            </div>
          )}

          {dataLoading && (
            <p className="loading-message">
              Loading workspace data...
            </p>
          )}

          {page === 'dashboard' && (
            <>
              <div className="page-intro">
                <div>
                  <h2>
                    Good to see you, {user.username || 'there'}!
                  </h2>
                  <p>Here's a summary of your workspace.</p>
                </div>

                <button
                  className="refresh-button"
                  onClick={loadWorkspace}
                >
                  ↻ Refresh data
                </button>
              </div>

              <div className="stats-grid">
                <StatCard
                  title="Total products"
                  value={products.length}
                  note="Products in catalog"
                />
                <StatCard
                  title="Inventory records"
                  value={inventory.length}
                  note="Stock records returned"
                />
                <StatCard
                  title="My orders"
                  value={orders.length}
                  note="Orders returned by service"
                />
                <StatCard
                  title="Cart items"
                  value={cart.length}
                  note={`Cart total: ${money(cartTotal)}`}
                />
              </div>

              <div className="section-card">
                <div className="section-header">
                  <div>
                    <h3>Recent products</h3>
                    <p>Your latest catalog entries.</p>
                  </div>
                  <button
                    className="text-button"
                    onClick={() => setPage('products')}
                  >
                    View products →
                  </button>
                </div>

                <ProductTable
                  products={products.slice(0, 5)}
                  onAdd={addToCart}
                  busyProductId={busyProductId}
                />
              </div>

              <div className="section-card">
                <div className="section-header">
                  <div>
                    <h3>Recent orders</h3>
                    <p>Orders associated with your account.</p>
                  </div>
                  <button
                    className="text-button"
                    onClick={() => setPage('orders')}
                  >
                    View orders →
                  </button>
                </div>

                <OrderTable orders={orders.slice(0, 5)} />
              </div>
            </>
          )}
                      {page === 'products' && (
            <>
              <div className="section-card">
                <div className="section-header">
                  <div>
                    <h3>Product catalog</h3>
                    <p>Browse products and add them to your cart.</p>
                  </div>

                  <div className="button-row">
                    <button
                      className="refresh-button"
                      onClick={refreshProducts}
                    >
                      ↻ Refresh
                    </button>

                    {isAdmin && (
                      <button
                        className="submit-button compact"
                        onClick={() =>
                          setShowProductForm((shown) => !shown)
                        }
                      >
                        {showProductForm ? 'Close form' : '+ Add product'}
                      </button>
                    )}
                  </div>
                </div>

                {showProductForm && isAdmin && (
                  <form
                    className="product-form"
                    onSubmit={createProduct}
                  >
                    <h3>Add a new product</h3>

                    <label>
                      Product name
                      <input
                        value={productForm.name}
                        onChange={(e) =>
                          setProductForm({
                            ...productForm,
                            name: e.target.value,
                          })
                        }
                        placeholder="e.g. Wireless Mouse"
                        required
                      />
                    </label>

                    <label>
                      Category
                      <input
                        value={productForm.category}
                        onChange={(e) =>
                          setProductForm({
                            ...productForm,
                            category: e.target.value,
                          })
                        }
                        placeholder="e.g. Electronics"
                      />
                    </label>

                    <label>
                      Price (₹)
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={productForm.price}
                        onChange={(e) =>
                          setProductForm({
                            ...productForm,
                            price: e.target.value,
                          })
                        }
                        placeholder="1999"
                        required
                      />
                    </label>

                    <label>
                      Description
                      <textarea
                        value={productForm.description}
                        onChange={(e) =>
                          setProductForm({
                            ...productForm,
                            description: e.target.value,
                          })
                        }
                        placeholder="Product details"
                        rows="3"
                      />
                    </label>

                    <button className="submit-button" disabled={loading}>
                      {loading ? 'Saving...' : 'Save product'}
                    </button>
                  </form>
                )}

                {!isAdmin && (
                  <p className="muted-note">
                    Product creation is available to administrator accounts.
                  </p>
                )}

                <input
                  className="search-input"
                  placeholder="Search products or categories..."
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />

                <ProductTable
                  products={filteredProducts}
                  onAdd={addToCart}
                  busyProductId={busyProductId}
                />
              </div>
            </>
          )}

          {page === 'inventory' && (
            <div className="section-card">
              <div className="section-header">
                <div>
                  <h3>Inventory</h3>
                  <p>
                    Stock and availability records from the inventory service.
                  </p>
                </div>
              </div>

              {canManageInventory && (
                <form className="product-form" onSubmit={adjustStock}>
                  <h3>Adjust Stock</h3>

                  <label>
                    Product
                    <select
                      value={stockAdjustment.product_id}
                      onChange={(event) =>
                        setStockAdjustment({
                          ...stockAdjustment,
                          product_id: event.target.value,
                        })
                      }
                      required
                    >
                      <option value="">Select a product</option>
                      {inventory.map((item) => {
                        const productId = item.product_id ?? item.id
                        const product = products.find(
                          (p) => Number(p.id) === Number(productId),
                        )

                        return (
                          <option key={productId} value={productId}>
                            {product?.name || `Product #${productId}`}
                          </option>
                        )
                      })}
                    </select>
                  </label>

                  <label>
                    Quantity change
                    <input
                      type="number"
                      value={stockAdjustment.change_quantity}
                      onChange={(event) =>
                        setStockAdjustment({
                          ...stockAdjustment,
                          change_quantity: event.target.value,
                        })
                      }
                      placeholder="Example: 5 or -2"
                      required
                    />
                  </label>

                  <label>
                    Reason
                    <input
                      type="text"
                      value={stockAdjustment.reason}
                      onChange={(event) =>
                        setStockAdjustment({
                          ...stockAdjustment,
                          reason: event.target.value,
                        })
                      }
                      placeholder="Example: New stock received"
                      minLength={3}
                      maxLength={250}
                      required
                    />
                  </label>

                  <button
                    type="submit"
                    className="submit-button"
                    disabled={stockLoading}
                  >
                    {stockLoading
                      ? 'Updating stock...'
                      : 'Save Stock Adjustment'}
                  </button>
                </form>
              )}

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Product ID</th>
                      <th>Quantity</th>
                      <th>Reserved</th>
                      <th>Available</th>
                      <th>Stock status</th>
                      <th>Transactions</th>
                    </tr>
                  </thead>

                  <tbody>
                    {inventory.map((item) => {
                      const productId = item.product_id ?? item.id
                      const available =
                        item.available_quantity ??
                        ((item.quantity || 0) -
                          (item.reserved_quantity || 0))
                      const low =
                        available <= (item.low_stock_threshold ?? 5)

                      return (
                        <tr key={productId}>
                          <td>#{productId}</td>
                          <td>{item.quantity ?? '—'}</td>
                          <td>{item.reserved_quantity ?? 0}</td>
                          <td>{available}</td>
                          <td>
                            <span
                              className={
                                low ? 'pill warning' : 'pill success'
                              }
                            >
                              {low ? 'Low stock' : 'In stock'}
                            </span>
                          </td>
                          <td>
                            <button
                              type="button"
                              className="refresh-button"
                              onClick={() => loadTransactions(productId)}
                            >
                              View history
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>

                {inventory.length === 0 && (
                  <EmptyState text="No inventory records were returned." />
                )}
              </div>

              {selectedTransactionProduct !== null && (
                <div className="section-card transaction-section">
                  <div className="section-header">
                    <div>
                      <h3>
                        Stock transaction history — Product #
                        {selectedTransactionProduct}
                      </h3>
                      <p>Recorded stock additions and deductions.</p>
                    </div>

                    <button
                      className="refresh-button"
                      onClick={() => {
                        setSelectedTransactionProduct(null)
                        setTransactions([])
                      }}
                    >
                      Close history
                    </button>
                  </div>

                  {transactionLoading ? (
                    <p className="loading-message">
                      Loading transaction history...
                    </p>
                  ) : (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Transaction ID</th>
                            <th>Quantity change</th>
                            <th>Reason</th>
                            <th>Responsible user</th>
                            <th>Date</th>
                          </tr>
                        </thead>

                        <tbody>
                          {transactions.map((transaction) => (
                            <tr key={transaction.id}>
                              <td>#{transaction.id}</td>
                              <td>
                                <span
                                  className={
                                    transaction.change_quantity > 0
                                      ? 'pill success'
                                      : 'pill warning'
                                  }
                                >
                                  {transaction.change_quantity > 0
                                    ? `+${transaction.change_quantity}`
                                    : transaction.change_quantity}
                                </span>
                              </td>
                              <td>{transaction.reason || '—'}</td>
                              <td>
                                {transaction.responsible_user_id ?? '—'}
                              </td>
                              <td>
                                {transaction.created_at
                                  ? new Date(
                                      transaction.created_at,
                                    ).toLocaleString('en-IN')
                                  : '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>

                      {transactions.length === 0 && (
                        <EmptyState text="No stock transactions found for this product." />
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
                    {page === 'cart' && (
            <div className="section-card">
              <div className="section-header">
                <div>
                  <h3>My cart</h3>
                  <p>Review item prices and your total before checkout.</p>
                </div>

                <button
                  className="refresh-button"
                  onClick={loadWorkspace}
                >
                  ↻ Refresh cart
                </button>
              </div>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Unit price</th>
                      <th>Quantity</th>
                      <th>Subtotal</th>
                      <th>Actions</th>
                    </tr>
                  </thead>

                  <tbody>
                    {cartRows.map((item) => (
                      <tr key={item.id}>
                        <td>{item.displayName}</td>
                        <td>
                          {item.displayPrice == null
                            ? 'Price unavailable'
                            : money(item.displayPrice)}
                        </td>
                        <td>
                          <div className="quantity-control">
                            <button
                              type="button"
                              disabled={busyCartId === item.id}
                              onClick={() =>
                                updateCartQuantity(
                                  item,
                                  item.displayQuantity - 1,
                                )
                              }
                              aria-label="Decrease quantity"
                            >
                              −
                            </button>

                            <strong>{item.displayQuantity}</strong>

                            <button
                              type="button"
                              disabled={busyCartId === item.id}
                              onClick={() =>
                                updateCartQuantity(
                                  item,
                                  item.displayQuantity + 1,
                                )
                              }
                              aria-label="Increase quantity"
                            >
                              +
                            </button>
                          </div>
                        </td>

                        <td>
                          {item.subtotal == null
                            ? '—'
                            : money(item.subtotal)}
                        </td>

                        <td>
                          <button
                            className="danger-button"
                            disabled={busyCartId === item.id}
                            onClick={() => removeFromCart(item)}
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {cart.length === 0 && (
                  <EmptyState text="Your cart is empty. Visit Products to add items." />
                )}
              </div>

              {cartRows.length > 0 && (
                <div className="cart-summary">
                  <div>
                    <span>Items</span>
                    <strong>
                      {cartRows.reduce(
                        (sum, item) => sum + item.displayQuantity,
                        0,
                      )}
                    </strong>
                  </div>

                  <div>
                    <span>Grand total</span>
                    <strong className="cart-total">
                      {cartHasUnknownPrice
                        ? 'Price unavailable'
                        : money(cartTotal)}
                    </strong>
                  </div>

                  <label className="shipping-field">
                    Shipping address
                    <input
                      value={shippingAddress}
                      onChange={(event) =>
                        setShippingAddress(event.target.value)
                      }
                      required
                    />
                  </label>

                  <button
                    className="submit-button checkout-button"
                    disabled={checkoutLoading || cartHasUnknownPrice}
                    onClick={checkout}
                  >
                    {checkoutLoading
                      ? 'Creating order...'
                      : `Checkout · ${money(cartTotal)}`}
                  </button>

                  <p className="muted-note">
                    Checkout creates an order and reserves stock. Payment is
                    handled separately by the Payment Service.
                  </p>
                </div>
              )}
            </div>
          )}

          {page === 'orders' && (
            <div className="section-card">
              <div className="section-header">
                <div>
                  <h3>Order history</h3>
                  <p>Orders associated with your account.</p>
                </div>

                <button
                  className="refresh-button"
                  onClick={loadWorkspace}
                >
                  ↻ Refresh
                </button>
              </div>

              <OrderTable orders={orders} />
            </div>
          )}
        </section>
      </main>
    </div>
  )
}

function StatCard({ title, value, note }) {
  return (
    <article className="stat-card">
      <span>{title}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  )
}

function ProductTable({ products, onAdd, busyProductId }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Product</th>
            <th>Category</th>
            <th>Price</th>
            <th>Product ID</th>
            <th>Action</th>
          </tr>
        </thead>

        <tbody>
          {products.map((product) => (
            <tr key={product.id}>
              <td>
                <div className="product-cell">
                  <span className="product-placeholder">□</span>
                  <strong>{productName(product)}</strong>
                </div>
              </td>

              <td>{product.category || 'General'}</td>

              <td>
                {productPrice(product) == null
                  ? 'Price unavailable'
                  : money(productPrice(product))}
              </td>

              <td>#{product.id ?? '—'}</td>

              <td>
                <button
                  className="submit-button compact"
                  disabled={!product.id || busyProductId === product.id}
                  onClick={() => onAdd(product)}
                >
                  {busyProductId === product.id
                    ? 'Adding...'
                    : 'Add to cart'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {products.length === 0 && (
        <EmptyState text="No products found. The catalog may be empty." />
      )}
    </div>
  )
}

function OrderTable({ orders }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Order</th>
            <th>Date</th>
            <th>Total</th>
            <th>Order status</th>
            <th>Payment status</th>
          </tr>
        </thead>

        <tbody>
          {orders.map((order) => (
            <tr key={order.id}>
              <td>#{order.id}</td>

              <td>
                {order.created_at
                  ? new Date(order.created_at).toLocaleDateString('en-IN')
                  : '—'}
              </td>

              <td>
                {order.total_amount == null
                  ? '—'
                  : money(order.total_amount)}
              </td>

              <td>
                <span className="pill neutral">
                  {order.status || 'pending'}
                </span>
              </td>

              <td>
                <span className="pill neutral">
                  {order.payment_status || 'unpaid'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {orders.length === 0 && (
        <EmptyState text="No orders to display yet." />
      )}
    </div>
  )
}

function EmptyState({ text }) {
  return <div className="empty-state">{text}</div>
}

export default App