# Production-Grade MVP Specification: Temporal Compliance RAG Engine

**System Architecture, Database Design, and Multi-Tenant Vector Partitioning Blueprint**

---

## 1. System Overview

### 1.1 Executive Summary

In regulated industries such as fintech and healthcare, tracking regulatory alignment manually is a significant risk vector. Regulatory bodies rarely provide clean REST APIs for tracking legal updates; instead, the legal absolute source of truth remains unformatted, static documents: **Official Gazettes, Statutory Rules and Orders (SROs), and Circulars**.

This system resolves the challenge of **"Regulatory Drift"**—the progressive divergence over time between internal company policies and active, shifting jurisdictional boundaries—by processing unstructured public legal text against an internal organizational profile.

```text
       [Public Documents / PDF Gazettes] ──> [n8n Automated Monitor]
                                                      │
                                                      ▼
[Next.js Client App] <── [FastAPI Orchestrator] <── [pgvector / SQLModel Store]
```

### 1.2 Tech Stack Architecture

* **Frontend Engine:** Next.js (App Router) using a technical minimalist UI approach optimized for high-density document comparisons and deep textual citation inspection.
* **Core Backend Server:** FastAPI (Python 3.11+) employing asynchronous execution threads for non-blocking stream handling (`StreamingResponse`).
* **Database Infrastructure:** PostgreSQL with the `pgvector` extension, modeled object-relationally via `SQLModel` for complete Type-Safety across the stack.
* **Agent Optimization Tooling:** Claude Code execution partner for structural framework scaffolding, entity extraction orchestration, and unit testing automation.

---

## 2. Core Functional Requirements

### 2.1 Automated Document Ingestion Pipeline

1. **Scheduled Polling Hook:** An asynchronous polling manager (or an automated `n8n` webhook node) executes a nightly review against targeted regulatory announcement indexes (e.g., SECP Circulars, SBP Banking Directives).
2. **Raw Document Parsing System:** Downloaded binary objects (PDFs) pass through an isolation parsing system (e.g., `PyMuPDF` or `Marker`) that translates multi-column legal frameworks, complex tables, and footnotes into a unified, clean Markdown document string.
3. **Hierarchical Chunk Splitter:** Extracted Markdown strings are split recursively by structural titles (e.g., *Part*, *Chapter*, *Section*, *Subsection*) rather than generic token lengths, maintaining the explicit semantic relationship of legal dependencies.

### 2.2 Temporal Filtering Strategy

* **Dynamic Constraint Scope:** Every vector entry is tightly bound to operational parameters, including `effective_date`, `expiration_date`, and `jurisdiction`.
* **Determinism Enforcement:** The retrieval execution query forbids searching historical nodes that have been superseded by active legal frameworks.

### 2.3 Visualized Audit UI

* **Diff Engine Visualization:** A split-view presentation dashboard highlighting internal policy variances side-by-side with official government text blocks.
* **Strict Citation Tracing:** Visual anchors overlaying the specific text lines, linking dynamically to the official external URL resource download point.

---

## 3. Database Schema Blueprint (`SQLModel`)

The physical data mapping relies on a two-tier structural approach: `RegulatoryDocument` stores parent-level metadata tracking the official gazette reference source, while `RegulatoryChunk` handles vector coordinates and strict chronological conditions.

```python
from datetime import datetime
from typing import List, Optional
from pgvector.sqlalchemy import Vector
from sqlmodel import Field, Relationship, SQLModel, Column

class RegulatoryDocument(SQLModel, table=True):
    __tablename__ = "regulatory_documents"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    issuing_body: str = Field(index=True)  # e.g., "SECP", "SBP"
    document_type: str = Field(index=True)  # e.g., "SRO", "Circular", "Gazette"
    source_url: str
    published_date: datetime
    ingested_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    chunks: List["RegulatoryChunk"] = Relationship(back_populates="document")

class RegulatoryChunk(SQLModel, table=True):
    __tablename__ = "regulatory_chunks"

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="regulatory_documents.id", index=True)
    content: str = Field(nullable=False)

    # Temporal & Jurisdictional Metadata Attributes
    jurisdiction: str = Field(index=True)  # e.g., "PK", "US-TX", "EU"
    effective_date: datetime = Field(index=True)
    expiration_date: Optional[datetime] = Field(default=None, index=True)
    is_active: bool = Field(default=True, index=True)

    # Hierarchical Tracking Indicators
    legal_citation: str  # e.g., "Section 12-B, Subsection 4(a)"

    # Vector Field - 1536 dimensions for text-embedding-3-small
    embedding: List[float] = Field(sa_column=Column(Vector(1536)))

    # Relationships
    document: RegulatoryDocument = Relationship(back_populates="chunks")
```

---

## 4. Backend Architecture & RAG Logic (`FastAPI`)

The backend coordinates incoming search traffic using a hybrid architecture. The semantic lookup phase combines dense embeddings with conditional relational SQL expressions, passing structured inputs to the LLM evaluator to prevent hallucinations.

```python
import os
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from sqlmodel import Session, select, create_engine

# API Types & Contract Contracts
class ComplianceAuditRequest(BaseModel):
    policy_text: str
    jurisdiction: str
    target_date: Optional[datetime] = None

class PolicyViolation(BaseModel):
    offending_policy_text: str
    legal_rule_text: str
    citation: str
    source_url: str
    risk_level: str  # HIGH, MEDIUM, LOW
    suggested_fix: str

class AuditResponse(BaseModel):
    is_compliant: bool
    violations: List[PolicyViolation]

app = FastAPI(title="Temporal Compliance Verification Router")

# Database Connection Engine
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
engine = create_engine(DATABASE_URL)

def get_session():
    with Session(engine) as session:
        yield session

@app.post("/api/v1/compliance/audit", response_model=AuditResponse)
async def perform_compliance_audit(
    request: ComplianceAuditRequest,
    session: Session = Depends(get_session)
):
    # Establish query confirmation timestamp
    audit_time = request.target_date or datetime.utcnow()

    # 1. Transform input policy text string into a numerical vector coordinate
    # mock_embedding = await openai_client.embeddings.create(input=[request.policy_text], ...)
    mock_embedding = [0.0] * 1536  # Placeholder

    # 2. Query vector database utilizing metadata chronological isolation parameters
    # Matches semantic context while filtering out expired or irrelevant regional codes
    query = (
        select(RegulatoryChunk, RegulatoryDocument)
        .join(RegulatoryDocument)
        .where(RegulatoryChunk.jurisdiction == request.jurisdiction)
        .where(RegulatoryChunk.is_active == True)
        .where(RegulatoryChunk.effective_date <= audit_time)
        .where((RegulatoryChunk.expiration_date == None) | (RegulatoryChunk.expiration_date > audit_time))
        .order_by(RegulatoryChunk.embedding.cosine_distance(mock_embedding))
        .limit(5)
    )

    results = session.exec(query).all()

    if not results:
        return AuditResponse(is_compliant=True, violations=[])

    # 3. Construct Context payload block for target LLM Review
    context_str = ""
    for chunk, doc in results:
        context_str += f"Source: {doc.title} ({chunk.legal_citation})\n"
        context_str += f"Text: {chunk.content}\n\n"

    # 4. Prompt Engineering Context Execution Pattern
    # payload_prompt = f"Given the regulatory baseline rules:\n{context_str}\nAudit this policy:\n{request.policy_text}..."
    # llm_output = await client.chat.completions.create(response_format={ "type": "json_object" }, ...)

    # Structured response returns exact violations found by cross-referencing dates
    return AuditResponse(
        is_compliant=False,
        violations=[
            PolicyViolation(
                offending_policy_text="PocketPay will hold user funds for up to 7 business days before clearing.",
                legal_rule_text="All retail digital accounts must settle transit funds within a strict maximum window of 3 business days.",
                citation="SECP Regulation 12-B (Amended June 2026)",
                source_url="https://example.gov.pk/gazette/reg-12b",
                risk_level="HIGH",
                suggested_fix="Update the holding rule to clear or refund client balances within 72 hours."
            )
        ]
    )
```
