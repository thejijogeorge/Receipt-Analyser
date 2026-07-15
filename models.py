import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Date, DateTime,
    ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class Receipt(Base):
    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True)
    filename = Column(String(255), nullable=False)
    receipt_date = Column(Date, nullable=True)
    store = Column(String(255), nullable=True)  # store location, e.g. "7572 - CS SCHOFIELDS"
    store_key = Column(String(100), nullable=True)  # stable identifier, e.g. "coles", "unknown_xyz"
    store_name = Column(String(255), nullable=True)  # display name, e.g. "Coles"
    processed_at = Column(DateTime, default=datetime.utcnow)

    items = relationship("ReceiptItem", back_populates="receipt", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("filename", name="uq_receipt_filename"),)


class ReceiptItem(Base):
    __tablename__ = "receipt_items"

    id = Column(Integer, primary_key=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id"), nullable=False)
    item_name = Column(String(255), nullable=False)
    real_name = Column(String(255), nullable=True)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, nullable=True)
    line_total = Column(Float, nullable=True)
    discount = Column(Float, nullable=True)

    receipt = relationship("Receipt", back_populates="items")


class GiftCard(Base):
    __tablename__ = "gift_cards"

    id = Column(Integer, primary_key=True)
    last_four = Column(String(30), nullable=False)
    balance = Column(Float, nullable=True)
    amount_redeemed = Column(Float, nullable=True)
    last_receipt_filename = Column(String(255), nullable=True)
    store_key = Column(String(100), nullable=True)
    updated_at = Column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("store_key", "last_four", name="uq_giftcard_store_last_four"),)


def get_engine():
    db_url = os.environ["DATABASE_URL"]
    return create_engine(db_url)


def get_session():
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()
