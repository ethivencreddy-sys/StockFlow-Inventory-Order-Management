# StockFlow – Inventory and Order Management System

StockFlow is a microservices-based inventory and order management platform built using Python, FastAPI, React, SQLite, Docker, RabbitMQ, and Redis.

The system supports product management, inventory tracking, shopping carts, orders, payments, notifications, reviews, coupons, returns, and sales analytics.

## Technology Stack

- **Backend:** Python 3.10, FastAPI
- **Frontend:** React, Vite
- **Database:** SQLite
- **API Gateway:** FastAPI
- **Message Broker:** RabbitMQ
- **Caching and Rate Limiting:** Redis
- **Background Processing:** Python worker
- **Containerization:** Docker and Docker Compose
- **Testing:** Pytest

## Architecture

StockFlow contains 11 independent microservices, an API Gateway, a React frontend, RabbitMQ, Redis, and an order-processing worker.

### Microservices

| Service | Host Port |
|---|---:|
| Authentication | 8011 |
| Product Catalog | 8012 |
| Inventory | 8013 |
| Cart and Wishlist | 8014 |
| Order Management | 8015 |
| Payment | 8016 |
| Notification | 8017 |
| Review and Rating | 8018 |
| Coupon and Discount | 8019 |
| Analytics and Reporting | 8020 |
| Return and Refund | 8021 |
| API Gateway | 8022 |
| React Frontend | 5175 |

### Infrastructure

| Component | Purpose |
|---|---|
| RabbitMQ | Asynchronous messaging |
| Redis | Gateway rate limiting |
| Order Worker | Background event processing |

## Application URLs

| Component | URL |
|---|---|
| React Frontend | http://localhost:5175 |
| API Gateway | http://localhost:8022 |
| RabbitMQ Management UI | http://localhost:15672 |

## Features

- User registration and authentication
- Product browsing and management
- Inventory tracking
- Shopping cart and wishlist
- Order creation and management
- Payment service integration
- Notification service
- Product reviews and ratings
- Coupon validation and redemption
- Return request management
- Sales analytics and reporting
- CSV analytics export
- RabbitMQ event processing with retry and dead-letter queues
- Redis-backed API rate limiting
- Docker-based service deployment

## Project Structure

```text
inventory-order-management/
├── api-gateway/
├── frontend/
├── services/
│   ├── analytics-service/
│   ├── auth-service/
│   ├── cart-service/
│   ├── coupon-service/
│   ├── inventory-service/
│   ├── notification-service/
│   ├── order-service/
│   ├── payment-service/
│   ├── product-service/
│   ├── return-service/
│   └── review-service/
├── tests/
├── docs/
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Prerequisites

Make sure the following tools are installed:

- Python 3.10 or later
- Node.js and npm
- Docker Desktop
- Git

## Environment Configuration

1. Create a `.env` file in the project root.
2. Use `.env.example` as the configuration template.
3. Configure the required secret keys and RabbitMQ credentials before starting the application.

**Security note:** Never commit `.env` files, passwords, access tokens, or local database files to GitHub.

## Running the Project

### 1. Start all services

From the project root, run:

```powershell
docker compose up -d --build
```

### 2. Check running containers

```powershell
docker compose ps
```

### 3. View service logs

```powershell
docker compose logs -f
```

### 4. Stop the application

```powershell