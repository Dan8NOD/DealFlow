"""SQLAlchemy ORM models for multi-tenant SaaS."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, Float, Index, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.db import Base


class PlanTier(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    TEAM = "team"


class UserRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    AGENT = "agent"
    MEMBER = "member"


class PropertyStatus(str, enum.Enum):
    AVAILABLE  = "AVAILABLE"
    RENTED     = "RENTED"
    OCCUPIED   = "OCCUPIED"
    OFF_MARKET = "OFF_MARKET"
    FOR_SALE   = "FOR_SALE"
    PENDING    = "PENDING"


class LeadStatus(str, enum.Enum):
    NEW       = "NEW"
    CONTACTED = "CONTACTED"
    QUALIFIED = "QUALIFIED"
    CLOSED    = "CLOSED"
    LOST      = "LOST"
    COLD      = "COLD"


class ApplicationStatus(str, enum.Enum):
    APPLICATION_RECEIVED = "APPLICATION_RECEIVED"
    OFFER_SENT           = "OFFER_SENT"
    WELCOME_SENT         = "WELCOME_SENT"
    APPROVED             = "APPROVED"
    LEASE_SIGNED         = "LEASE_SIGNED"
    MOVED_IN             = "MOVED_IN"
    DENIED               = "DENIED"


class SalesStatus(str, enum.Enum):
    NEW_LISTING_ALERT = "NEW_LISTING_ALERT"
    CMA_REQUESTED     = "CMA_REQUESTED"
    LISTING_PREP      = "LISTING_PREP"
    ACTIVE_LISTING    = "ACTIVE_LISTING"
    IN_ESCROW         = "IN_ESCROW"
    UNDER_CONTRACT    = "UNDER_CONTRACT"
    CONTRACT_SIGNED   = "CONTRACT_SIGNED"
    OFFER_RECEIVED    = "OFFER_RECEIVED"
    CLOSED            = "CLOSED"


class Organization(Base):
    __tablename__ = "organizations"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    plan = Column(Enum(PlanTier), default=PlanTier.FREE, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    stripe_customer_id = Column(String(100), index=True)
    users = relationship("User", back_populates="organization", cascade="all, delete")
    properties = relationship("Property", back_populates="organization", cascade="all, delete")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    email = Column(String(200), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(200))
    role = Column(Enum(UserRole), default=UserRole.OWNER, nullable=False)
    is_active = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())
    last_login_at = Column(DateTime)
    organization = relationship("Organization", back_populates="users")


class Property(Base):
    __tablename__ = "properties"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    address = Column(String(300), nullable=False, index=True)
    unit = Column(String(50))
    city = Column(String(100))
    state = Column(String(2))
    zip_code = Column(String(10))
    bedrooms = Column(Float)
    bathrooms = Column(Float)
    square_feet = Column(Integer)
    rent = Column(Float)
    status = Column(Enum(PropertyStatus), default=PropertyStatus.AVAILABLE)
    tenant_name = Column(String(200))
    available_date = Column(DateTime)
    notes = Column(Text)
    # ── Obsidian-enriched fields ──
    pet_restrictions = Column(Text, comment="from Obsidian LEASING notes")
    utilities_included = Column(Text, comment="heat, water, etc. included in rent")
    utilities_paid_by_tenant = Column(Text, comment="electric, gas, etc. paid by tenant")
    parking = Column(Text, comment="parking details and rent if applicable")
    storage = Column(Text, comment="storage details")
    laundry = Column(Text, comment="laundry facilities")
    asset_manager = Column(String(200))
    lockbox_code = Column(String(100))
    listing_description = Column(Text, comment="marketing description")
    mls_id = Column(String(50))
    cma_link = Column(Text, comment="CloudCMA URL")
    showing_instructions = Column(Text, comment="e.g. use ShowingTime, lockbox location")
    created_at = Column(DateTime, server_default=func.now())
    organization = relationship("Organization", back_populates="properties")
    leads = relationship("Lead", back_populates="property", cascade="all, delete")
    __table_args__ = (Index("ix_property_org_addr", "org_id", "address"),)


class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), index=True)
    name = Column(String(200))
    email = Column(String(200), index=True)
    phone = Column(String(50), index=True)
    source = Column(String(100))
    status = Column(Enum(LeadStatus), default=LeadStatus.NEW)
    subject = Column(Text)
    received_at = Column(DateTime, nullable=False, index=True)
    days_old = Column(Integer)
    raw_email_id = Column(String(200), index=True)
    monthly_income = Column(Float)  # monthly income if known
    income_source = Column(String(50))  # 'application', 'self-reported', 'estimated'
    interested_in_buying = Column(Boolean, default=False)
    upsell_eligible = Column(Boolean, default=False)  # auto-flagged: income > threshold
    notes = Column(Text)  # agent notes
    # ── Spreadsheet / call-tracking fields ──
    move_in_date = Column(String(30), comment="desired move-in date from lead")
    last_called = Column(DateTime, comment="last call attempt timestamp")
    call_outcome = Column(String(100), comment="e.g. Left Voicemail, No Answer, Qualified")
    call_notes = Column(Text, comment="notes from phone outreach")
    bounce_to = Column(Text, comment="suggested alternative properties to bounce lead to")
    assigned_agent_id = Column(Integer, ForeignKey("users.id"), index=True, comment="assigned agent")
    created_at = Column(DateTime, server_default=func.now())
    property = relationship("Property", back_populates="leads")
    assigned_agent = relationship("User", foreign_keys=[assigned_agent_id])


class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), index=True)
    unit = Column(String(50))
    applicant_name = Column(String(200), index=True)
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.APPLICATION_RECEIVED)
    handler = Column(String(200))
    first_seen = Column(DateTime)
    last_update = Column(DateTime)
    days_in_pipeline = Column(Integer)
    event_count = Column(Integer, default=0)
    needs_review = Column(Boolean, default=False)
    monthly_income = Column(Float)  # from application docs
    credit_score = Column(Integer)
    move_in_date = Column(String(30))
    pets = Column(String(100))
    notes = Column(Text)  # agent notes
    created_at = Column(DateTime, server_default=func.now())
    events = relationship("ApplicationEvent", back_populates="application", cascade="all, delete")
    property = relationship("Property")


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)
    occurred_at = Column(DateTime, nullable=False)
    handler = Column(String(200))
    source_email_id = Column(String(200))
    subject = Column(Text)
    application = relationship("Application", back_populates="events")


class SalesDeal(Base):
    __tablename__ = "sales_deals"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    property_address = Column(String(300), nullable=False, index=True)
    status = Column(Enum(SalesStatus), default=SalesStatus.ACTIVE_LISTING)
    list_price = Column(Float)
    transaction_coordinator = Column(String(200))
    first_seen = Column(DateTime)
    last_update = Column(DateTime)
    days_idle = Column(Integer)
    event_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class CmaRequest(Base):
    __tablename__ = "cma_requests"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    property_address = Column(String(300), nullable=False, index=True)
    unit = Column(String(50))
    kind = Column(String(20))  # 'rental' or 'sale'
    status = Column(String(30), default="pending")
    request_count = Column(Integer, default=1)
    first_request = Column(DateTime)
    last_request = Column(DateTime)
    listed_at = Column(DateTime)


class PropertyFile(Base):
    __tablename__ = "property_files"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), index=True)
    kind = Column(String(30))
    name = Column(String(500))
    path = Column(String(1000))
    source = Column(String(50))  # 'icloud', 'gdrive', 'onedrive', 'upload'
    size_bytes = Column(Integer)
    obsidian_vault = Column(String(50))
    section = Column(String(50))  # 'LEASING' or 'SALES'
    created_at = Column(DateTime, server_default=func.now())


class EmailAccount(Base):
    """Connected email account (Microsoft Graph, Gmail, or IMAP) per org."""
    __tablename__ = "email_accounts"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    provider = Column(String(20), nullable=False)  # 'microsoft' | 'google' | 'imap'
    email_address = Column(String(200), nullable=False)
    access_token = Column(Text)
    refresh_token = Column(Text)
    token_expires_at = Column(DateTime)
    webhook_id = Column(String(200))
    webhook_expires_at = Column(DateTime)
    last_sync_at = Column(DateTime)
    sync_cursor = Column(String(200))  # delta token or last seen message id
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class Comment(Base):
    """User comments on any record — applications, leads, sales, properties, CMAs."""
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    record_type = Column(String(30), nullable=False, index=True)  # 'application' | 'lead' | 'sales_deal' | 'cma' | 'property'
    record_id = Column(Integer, nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    user = relationship("User")
    __table_args__ = (Index("ix_comment_record", "record_type", "record_id"),)


class EmailMessage(Base):
    """Raw email captured from an email account, before parsing into leads/applications/sales."""
    __tablename__ = "email_messages"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    email_account_id = Column(Integer, ForeignKey("email_accounts.id"), index=True)
    external_id = Column(String(200), unique=True, index=True)  # Graph message id
    subject = Column(Text)
    sender_email = Column(String(200), index=True)
    sender_name = Column(String(200))
    received_at = Column(DateTime, index=True)
    body_preview = Column(Text)
    is_processed = Column(Boolean, default=False)
    matched_property_id = Column(Integer, ForeignKey("properties.id"), nullable=True)
    matched_kind = Column(String(30))  # 'lead' | 'application' | 'sales_deal' | 'cma' | None
    created_at = Column(DateTime, server_default=func.now())
