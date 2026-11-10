
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Review
from app.schemas import ReviewCreate, ReviewResponse, ReviewUpdate
from app.security import get_current_user, require_roles

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Product Reviews Service",
    description="Create, retrieve, update, and delete product reviews",
    version="1.0.0",
)


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "review-service",
    }


@app.post(
    "/reviews",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_review(
    review_data: ReviewCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user["user_id"]

    existing_review = (
        db.query(Review)
        .filter(
            Review.user_id == user_id,
            Review.product_id == review_data.product_id,
        )
        .first()
    )

    if existing_review:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already reviewed this product",
        )

    review = Review(
        user_id=user_id,
        product_id=review_data.product_id,
        rating=review_data.rating,
        comment=review_data.comment,
    )

    db.add(review)

    try:
        db.commit()
        db.refresh(review)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A review for this product already exists",
        )

    return review


@app.get("/reviews", response_model=list[ReviewResponse])
def list_reviews(
    product_id: int | None = Query(default=None, gt=0),
    user_id: int | None = Query(default=None, gt=0),
    rating: int | None = Query(default=None, ge=1, le=5),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Review)

    if product_id is not None:
        query = query.filter(Review.product_id == product_id)

    if user_id is not None:
        query = query.filter(Review.user_id == user_id)

    if rating is not None:
        query = query.filter(Review.rating == rating)

    return (
        query.order_by(Review.created_at.desc(), Review.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )


@app.get("/reviews/summary/{product_id}")
def get_review_summary(
    product_id: int,
    db: Session = Depends(get_db),
):
    if product_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Product ID must be positive",
        )

    result = (
        db.query(func.count(Review.id), func.avg(Review.rating))
        .filter(Review.product_id == product_id)
        .first()
    )

    total_reviews = result[0] or 0
    average_rating = (
        round(float(result[1]), 2)
        if result[1] is not None
        else 0.0
    )

    return {
        "product_id": product_id,
        "total_reviews": total_reviews,
        "average_rating": average_rating,
    }


@app.get("/reviews/{review_id}", response_model=ReviewResponse)
def get_review(
    review_id: int,
    db: Session = Depends(get_db),
):
    review = db.query(Review).filter(Review.id == review_id).first()

    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    return review


@app.patch("/reviews/{review_id}", response_model=ReviewResponse)
def update_review(
    review_id: int,
    review_data: ReviewUpdate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    review = (
        db.query(Review)
        .filter(
            Review.id == review_id,
            Review.user_id == user["user_id"],
        )
        .first()
    )

    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    updates = review_data.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a rating or comment to update",
        )

    for field, value in updates.items():
        setattr(review, field, value)

    try:
        db.commit()
        db.refresh(review)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not update review",
        )

    return review


@app.delete("/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_review(
    review_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    review = (
        db.query(Review)
        .filter(
            Review.id == review_id,
            Review.user_id == user["user_id"],
        )
        .first()
    )

    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found",
        )

    db.delete(review)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
