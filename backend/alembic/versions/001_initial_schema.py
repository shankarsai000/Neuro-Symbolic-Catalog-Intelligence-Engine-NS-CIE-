"""Initial NS-CIE production schema for all 12 entities

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-08-18 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. products table
    op.create_table(
        'products',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('mfg_part_num', sa.String(length=128), nullable=False),
        sa.Column('part_desc', sa.Text(), nullable=False),
        sa.Column('raw_manuf', sa.String(length=255), nullable=True),
        sa.Column('canonical_brand', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=64), server_default='pending', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_products_mpn_brand', 'products', ['mfg_part_num', 'canonical_brand'])
    op.create_index('idx_products_status_created', 'products', ['status', 'created_at'])
    op.create_index('ix_products_mfg_part_num', 'products', ['mfg_part_num'])
    op.create_index('ix_products_canonical_brand', 'products', ['canonical_brand'])
    op.create_index('ix_products_status', 'products', ['status'])

    # 2. batch_jobs table
    op.create_table(
        'batch_jobs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('total_items', sa.Integer(), server_default='0', nullable=False),
        sa.Column('processed_items', sa.Integer(), server_default='0', nullable=False),
        sa.Column('high_confidence_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('review_needed_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('average_confidence', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('status', sa.String(length=64), server_default='pending', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_batch_jobs_status_created', 'batch_jobs', ['status', 'created_at'])
    op.create_index('ix_batch_jobs_status', 'batch_jobs', ['status'])

    # 3. enrichment_runs table
    op.create_table(
        'enrichment_runs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('batch_job_id', sa.Integer(), sa.ForeignKey('batch_jobs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('source_mode', sa.String(length=64), server_default='OFFLINE_HEURISTIC', nullable=False),
        sa.Column('model_used', sa.String(length=128), nullable=True),
        sa.Column('confidence_score', sa.Float(), server_default='1.0', nullable=False),
        sa.Column('provenance_score', sa.Float(), server_default='1.0', nullable=False),
        sa.Column('lov_score', sa.Float(), server_default='1.0', nullable=False),
        sa.Column('rule_score', sa.Float(), server_default='1.0', nullable=False),
        sa.Column('invoice_desc', sa.String(length=40), nullable=False),
        sa.Column('mobile_desc', sa.String(length=100), nullable=False),
        sa.Column('product_title', sa.String(length=255), nullable=False),
        sa.Column('long_desc', sa.Text(), nullable=False),
        sa.Column('short_desc', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=64), server_default='completed', nullable=False),
        sa.Column('execution_time_ms', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_enrichment_product_created', 'enrichment_runs', ['product_id', 'created_at'])
    op.create_index('ix_enrichment_runs_product_id', 'enrichment_runs', ['product_id'])
    op.create_index('ix_enrichment_runs_batch_job_id', 'enrichment_runs', ['batch_job_id'])

    # 4. extracted_attributes table
    op.create_table(
        'extracted_attributes',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('enrichment_run_id', sa.Integer(), sa.ForeignKey('enrichment_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('attribute_label', sa.String(length=128), nullable=False),
        sa.Column('attribute_value', sa.Text(), nullable=False),
        sa.Column('attribute_uom', sa.String(length=32), nullable=True),
        sa.Column('source_url', sa.String(length=512), nullable=True),
        sa.Column('source_type', sa.String(length=64), server_default='distributor_feed', nullable=False),
        sa.Column('evidence_text', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), server_default='1.0', nullable=False),
        sa.Column('is_lov_validated', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )
    op.create_index('idx_extracted_attr_run_label', 'extracted_attributes', ['enrichment_run_id', 'attribute_label'])
    op.create_index('ix_extracted_attributes_enrichment_run_id', 'extracted_attributes', ['enrichment_run_id'])

    # 5. sources table
    op.create_table(
        'sources',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('brand', sa.String(length=128), nullable=False),
        sa.Column('mpn', sa.String(length=128), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column('source_url', sa.String(length=512), nullable=False),
        sa.Column('source_type', sa.String(length=64), server_default='html', nullable=False),
        sa.Column('http_status', sa.Integer(), server_default='200', nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('raw_text', sa.Text(), nullable=False),
        sa.Column('parsed_evidence_json', sa.JSON(), nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('brand', 'mpn', name='uq_source_brand_mpn'),
    )
    op.create_index('idx_source_domain_brand', 'sources', ['domain', 'brand'])
    op.create_index('ix_sources_brand', 'sources', ['brand'])
    op.create_index('ix_sources_mpn', 'sources', ['mpn'])

    # 6. source_evidences table
    op.create_table(
        'source_evidences',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('source_id', sa.Integer(), sa.ForeignKey('sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('spec_key', sa.String(length=128), nullable=False),
        sa.Column('raw_snippet', sa.Text(), nullable=False),
        sa.Column('extracted_value', sa.String(length=255), nullable=False),
        sa.Column('confidence', sa.Float(), server_default='1.0', nullable=False),
    )
    op.create_index('idx_source_evidence_source_key', 'source_evidences', ['source_id', 'spec_key'])
    op.create_index('ix_source_evidences_source_id', 'source_evidences', ['source_id'])

    # 7. review_queue table
    op.create_table(
        'review_queue',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('enrichment_run_id', sa.Integer(), sa.ForeignKey('enrichment_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('batch_job_id', sa.Integer(), sa.ForeignKey('batch_jobs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('field_name', sa.String(length=128), nullable=False),
        sa.Column('original_value', sa.Text(), nullable=True),
        sa.Column('suggested_value', sa.Text(), nullable=True),
        sa.Column('current_value', sa.Text(), nullable=True),
        sa.Column('reason', sa.String(length=255), nullable=False),
        sa.Column('confidence', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('status', sa.String(length=64), server_default='PENDING', nullable=False),
        sa.Column('assigned_to', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_review_status_product', 'review_queue', ['status', 'product_id'])
    op.create_index('idx_review_created_status', 'review_queue', ['created_at', 'status'])
    op.create_index('ix_review_queue_product_id', 'review_queue', ['product_id'])
    op.create_index('ix_review_queue_status', 'review_queue', ['status'])

    # 8. review_actions table
    op.create_table(
        'review_actions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('review_id', sa.Integer(), sa.ForeignKey('review_queue.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action_type', sa.String(length=64), nullable=False),
        sa.Column('previous_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('user_notes', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_review_actions_review_time', 'review_actions', ['review_id', 'timestamp'])
    op.create_index('ix_review_actions_review_id', 'review_actions', ['review_id'])

    # 9. benchmark_runs table
    op.create_table(
        'benchmark_runs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('dataset_path', sa.String(length=512), nullable=False),
        sa.Column('total_rows', sa.Integer(), server_default='0', nullable=False),
        sa.Column('exact_match_rate', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('field_accuracy', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('category_accuracy', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('schema_compliance', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('uom_compliance', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('fraction_compliance', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('invoice_compliance', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('status', sa.String(length=64), server_default='completed', nullable=False),
        sa.Column('report_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_benchmark_run_status_created', 'benchmark_runs', ['status', 'created_at'])

    # 10. benchmark_results table
    op.create_table(
        'benchmark_results',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('benchmark_run_id', sa.Integer(), sa.ForeignKey('benchmark_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('row_index', sa.Integer(), nullable=False),
        sa.Column('mpn', sa.String(length=128), nullable=False),
        sa.Column('is_exact_match', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('field_scores_json', sa.JSON(), nullable=False),
        sa.Column('errors_json', sa.JSON(), nullable=False),
    )
    op.create_index('idx_benchmark_results_run_row', 'benchmark_results', ['benchmark_run_id', 'row_index'])
    op.create_index('ix_benchmark_results_benchmark_run_id', 'benchmark_results', ['benchmark_run_id'])

    # 11. schema_validation_results table
    op.create_table(
        'schema_validation_results',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('batch_id', sa.Integer(), sa.ForeignKey('batch_jobs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('total_rows', sa.Integer(), server_default='0', nullable=False),
        sa.Column('valid_rows', sa.Integer(), server_default='0', nullable=False),
        sa.Column('invalid_rows', sa.Integer(), server_default='0', nullable=False),
        sa.Column('column_count_valid', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('headers_valid', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('order_valid', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('error_log_json', sa.JSON(), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_schema_validation_results_batch_id', 'schema_validation_results', ['batch_id'])

    # 12. audit_events table
    op.create_table(
        'audit_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('event_type', sa.String(length=128), nullable=False),
        sa.Column('entity_type', sa.String(length=128), nullable=False),
        sa.Column('entity_id', sa.String(length=128), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_audit_events_type_entity', 'audit_events', ['event_type', 'entity_type', 'entity_id'])
    op.create_index('idx_audit_events_timestamp', 'audit_events', ['timestamp'])
    op.create_index('ix_audit_events_event_type', 'audit_events', ['event_type'])


def downgrade() -> None:
    op.drop_table('audit_events')
    op.drop_table('schema_validation_results')
    op.drop_table('benchmark_results')
    op.drop_table('benchmark_runs')
    op.drop_table('review_actions')
    op.drop_table('review_queue')
    op.drop_table('source_evidences')
    op.drop_table('sources')
    op.drop_table('extracted_attributes')
    op.drop_table('enrichment_runs')
    op.drop_table('batch_jobs')
    op.drop_table('products')
