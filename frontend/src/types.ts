export type Dictionary = Record<string, unknown>

export interface Organization {
  org_id: string
  name: string
  org_type: string
}

export interface Project {
  project_id: string
  notice_id: string
  title: string
  project_no?: string | null
  publish_date?: string | null
}

export interface GraphData {
  nodes: Array<{ id: string; name: string; type: string }>
  edges: Array<{
    source: string
    target: string
    type: string
    amount_yuan?: number | null
    quote_value?: number | null
    quote_unit?: string | null
    quote_text?: string | null
    score?: number | null
    rank?: number | null
  }>
}

export interface Job {
  job_id: string
  kind: string
  status: string
  stage: string
  progress: number
  file_count: number
  success_count: number
  failure_count: number
  message?: string
  created_at?: string
  files?: Array<{ file_name: string; status: string; error?: string | null }>
}

export interface PlatformStatus {
  task1: { entities: number; notices: number }
  task2: { projects: number; packages: number; organizations: number; bids: number; products: number }
  jobs: Job[]
  model: { status: string; message: string }
}

export interface Task1Item extends Dictionary {
  entity_id: string
  notice_id: string
  title: string
  item_no: number
  product_service_name?: string | null
  category_name?: string | null
  category_code?: string | null
  brand_supplier?: string | null
  spec_model?: string | null
  unit_price?: number | null
  quantity?: number | null
  quantity_unit?: string | null
  total_price?: number | null
  source_file?: string | null
  source_block_id?: string | null
  source_block_row?: number | null
  evidence_refs?: Array<{ block_id: string; block_row?: number | null }>
  evidence_excerpt?: string | null
}
