# StockFlow â€“ Inventory and Order Management System

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

RabbitMQ Management UI: http://localhost:15672

Frontend: http://localhost:5175

API Gateway: http://localhost:8022

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
â”œâ”€â”€ api-gateway/
â”œâ”€â”€ frontend/
â”œâ”€â”€ services/
â”‚   â”œâ”€â”€ analytics-service/
â”‚   â”œâ”€â”€ auth-service/
â”‚   â”œâ”€â”€ cart-service/
â”‚   â”œâ”€â”€ coupon-service/
â”‚   â”œâ”€â”€ inventory-service/
â”‚   â”œâ”€â”€ notification-service/
â”‚   â”œâ”€â”€ order-service/
â”‚   â”œâ”€â”€ payment-service/
â”‚   â”œâ”€â”€ product-service/
â”‚   â”œâ”€â”€ return-service/
â”‚   â””â”€â”€ review-service/
â”œâ”€â”€ tests/
â”œâ”€â”€ docs/
â”œâ”€â”€ docker-compose.yml
â”œâ”€â”€ requirements.txt
â”œâ”€â”€ .env.example
â”œâ”€â”€ .gitignore
â””â”€â”€ README.md
```

## Prerequisites

- Python 3.10 or later
- Node.js and npm
- Docker Desktop
- Git

## Environment Configuration

Create a `.env` file in the project root using `.env.example` as a template.

Configure the required secret keys and RabbitMQ credentials before starting the application.

Never commit `.env`, passwords, access tokens, or local database files.

## Running the Project

From the project root, start the services using:

```powershell
docker compose up -d --build
```

Check running containers:

```powershell
docker compose ps
```

Check service logs:

```powershell
docker compose logs -f
```

Stop the application:

```powershell
docker compose down
```

Persistent RabbitMQ and Redis data are stored in Docker volumes.

## API Documentation

FastAPI services expose Swagger documentation at `/docs` on their respective host ports.

Example:

- Gateway: http://localhost:8022/docs
- Authentication: http://localhost:8011/docs
- Products: http://localhost:8012/docs
- Inventory: http://localhost:8013/docs
- Orders: http://localhost:8015/docs

## Testing

Activate the Python virtual environment and run:

```powershell
python -m pytest -v
```

The current automated test suite contains 24 tests, all of which passed in the latest verification.

## Security

- JWT-based authentication
- Password hashing
- Environment-based secret configuration
- Sensitive files excluded through `.gitignore`
- Redis-backed API rate limiting
- RabbitMQ retry and dead-letter handling
- Service-level health endpoints

## Project Status
The Docker Compose environment includes 11 microservices, an API Gateway, a React frontend, RabbitMQ, Redis, and an order-processing worker.
The latest verification completed successfully:
- 24 automated tests passed.
- React production build passed.
- All 16 Docker containers were running.
- RabbitMQ and Redis reported healthy status.