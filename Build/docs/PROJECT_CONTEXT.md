# ORDER ORCHESTRATION PROJECT CONTEXT

## Purpose


Inventory allocation engine that executes:

- VOR
- ACC
- PUSH
- REPLENISHMENT

Sources:

- Parent RDC
- Cluster RDC
- PAN India RDC
- VEPDC
- GIT


## Current Replenishment Logic


Colour codes 16-20 use two-pass execution.

PASS 1:

Parent-only allocation.

PASS 2:

GIT and alternatives.

ZFMO 16:
- Credit block ignored
- No safety stock deduction anywhere
- ZFMO colour-16 scoring

ZMSO 16:
- Credit block enforced
- Parent no safety stock deduction
- Alternative safety stock deducted
- ZMSO colour-16 scoring

ZFMO 17-20:
- Credit block ignored
- Parent no safety stock deduction
- Alternative safety stock deducted
- Standard scoring

ZMSO 17-20:
- Credit block enforced
- Parent no safety stock deduction
- Alternative safety stock deducted
- Standard scoring


## Enums

### OrderType

- VOR
- ACC
- REPLENISHMENT
- PUSH

## Domain Models

### SourceType

- PARENT_RDC
- PARENT_GIT
- CLUSTER_RDC
- PAN_INDIA_RDC
- VEPDC

## Domain Models

### DecisionType

- ALLOCATE
- HOLD_FOR_GIT
- NO_ELIGIBLE_STOCK
- DATA_EXCEPTION
- RULE_EXCEPTION

## Domain Models

### TransportMode

- MILK_RUN
- AIR
- SURFACE
- PART_TRUCK_LOAD
- FULL_TRUCK_LOAD
- COURIER_EXPRESS

## Domain Models

### ReasonCode

- PUSH_PARENT_MOQ_ALLOCATION
- PUSH_SINGLE_SOURCE_AGEING_ALLOCATION
- PUSH_MULTI_SOURCE_AGEING_ALLOCATION
- PUSH_WEIGHTED_SCORE_FALLBACK
- AGEING_STOCK_PREFERRED
- MOQ_NOT_FOUND_DEFAULT_ONE_USED
- ORDER_QTY_PARTIALLY_MOQ_ALIGNED
- MOQ_REMAINDER_HELD_AT_PARENT
- PARENT_MOQ_PARTIAL_ALLOCATION
- MULTI_SOURCE_MOQ_ALLOCATION
- MAXIMUM_MOQ_ALIGNED_ALLOCATION
- INSUFFICIENT_MOQ_ALIGNED_STOCK
- REMAINING_QTY_HELD_AT_PARENT
- REPLENISHMENT_PARENT_ONLY_COLOUR_CODE
- REPLENISHMENT_REROUTE_ALLOWED_COLOUR_CODE
- PARENT_ONLY_FULL_FILL
- PARENT_ONLY_STOCK_INSUFFICIENT
- INVALID_REPLENISHMENT_COLOUR_CODE
- PARENT_FULL_FILL
- PARENT_INSUFFICIENT_QUANTITY
- PARENT_NO_ELIGIBLE_STOCK
- SAFETY_STOCK_PROTECTED
- WAIT_FOR_PARENT_GIT
- PARENT_GIT_OUTSIDE_THRESHOLD
- PARENT_GIT_INSUFFICIENT
- CLUSTER_FULL_FILL
- PAN_INDIA_FULL_FILL
- VEPDC_FULL_FILL
- ALTERNATIVE_FULL_FILL
- MAXIMUM_PARTIAL_FILL
- SINGLE_SOURCE_REROUTE
- SHORTEST_SLA_SELECTED
- LOWEST_COST_SELECTED
- SOURCE_PRIORITY_SELECTED
- SLA_SATISFIED
- SLA_NOT_SATISFIED
- NO_TRANSPORT_CONNECTIVITY
- INSUFFICIENT_QUANTITY
- NO_ELIGIBLE_STOCK
- NO_STOCK_AT_SOURCE
- MISSING_MASTER_DATA
- INVALID_ORDER_TYPE
- DUPLICATE_ORDER_EXECUTION
- INVENTORY_REVALIDATION_FAILED
- NEGATIVE_INVENTORY_PREVENTED
- ROUTE_NOT_EFFECTIVE
- TRANSPORT_MODE_NOT_ALLOWED
- INVALID_ROUTE_SLA
- INVALID_TRANSPORT_COST
- CREDIT_BLOCKED
- SLA_DATA_NOT_FOUND
- NON_AUTO_CUSTOMER_VEPDC_ONLY
- NON_AUTO_CUSTOMER_REROUTE_NOT_ALLOWED
- RLT_TIE_BREAK_SELECTED
- DATA_EXCEPTION
- RULE_EXCEPTION
- WEIGHTED_SCORE_SELECTED
- VOR_CREDIT_BLOCK_IGNORED
- ALLOWABLE_QTY_APPLIED
- ALLOWABLE_QTY_MISSING
- MILK_RUN_SELECTED
- MILK_RUN_NOT_AVAILABLE
- AIR_SELECTED_FOR_FASTEST_SLA
- SURFACE_SELECTED_FOR_FASTEST_SLA
- TRANSPORT_MODE_SELECTED_BY_LOWEST_COST
- FASTEST_DELIVERY_SELECTED
- PARENT_FULL_FILL_FORCED
- SURFACE_SELECTED_AS_PART_TRUCK_LOAD
- PUSH_AGEING_PARTIAL_FILL
- REMAINING_QTY_RETURNED_TO_PARENT
- NO_ELIGIBLE_PARENT_GIT_WITHIN_ONE_DAY
- REPLENISHMENT_PARENT_GIT_WITHIN_ONE_DAY
- GIT_DEFERRED_ALLOCATION
- PARENT_GIT_FULL_FILL
- PARENT_GIT_PARTIAL_FILL

## Domain Models

### SourceAllocation

- candidate
- allocated_quantity
- allocation_sequence
- inventory_movement

### MOQAllocationResult

- original_requested_quantity
- moq_qty
- moq_default_used
- moq_eligible_quantity
- moq_remainder_quantity
- total_allocated_quantity
- total_git_reserved_quantity
- total_fulfilled_quantity
- remaining_quantity
- allocations
- git_reservations
- reason_codes
- candidate_score_lookup

### ReplenishmentGitCandidate

- shipment
- arrival_days_from_decision
- eligible_quantity
- moq_aligned_capacity
- full_fill_capable

### ReplenishmentGitAllocationResult

- candidate
- reserved_quantity
- remaining_quantity
- movement
- reason_codes

### DeliveryCalculationResult

- expected_dispatch
- expected_delivery
- standard_sla_days
- pickup_buffer_hours
- drop_buffer_hours
- transport_cost

### LocationWorkingRule

- is_working
- work_start_time
- work_end_time
- allowed_order_types

### WorkingCalendarConfig

- working_days
- work_start_time
- work_end_time
- holidays
- timezone_name

### ValidationIssue

- table_name
- row_index
- field_name
- issue_code
- issue_message
- severity

### CandidateSource

- location
- source_type
- material_code
- requested_quantity
- available_quantity
- safety_stock
- eligible_quantity
- full_fill_capable
- ageing_quantity
- cluster
- region
- route_available
- allowed_transport_modes
- selected_transport_mode
- configured_sla_days
- rlt_days
- transport_cost
- expected_dispatch
- expected_delivery
- eligible
- rejection_reason_codes
- norms
- norms_found
- safety_stock_exempt_due_to_norms
- mad
- mad_default_used
- calculated_safety_stock
- safety_stock_protected
- safety_stock_policy
- route_default_used
- sla_default_used
- rlt_default_used
- master_data_default_used

### Decision

- order_id
- line_id
- order_type
- material_code
- dealer_code
- parent_rdc
- decision_timestamp
- decision
- requested_quantity
- allocated_quantity
- remaining_quantity
- selected_source
- selected_source_type
- transport_mode
- expected_dispatch
- expected_delivery
- configured_sla_hours
- transport_cost
- first_fill_rate
- reason_codes
- business_explanation
- candidate_evaluations
- rule_version
- configuration_version

### GitShipment

- material_code
- source_location
- destination_location
- git_quantity
- expected_arrival_datetime
- status

### InventoryPosition

- snapshot_timestamp
- location
- material_code
- actual_stock
- allocated_quantity
- pending_so_quantity
- safety_stock
- ageing_quantity
- ageing_quantity_gt_1yr

### InventoryMovement

- movement_id
- order_id
- line_id
- material_code
- location
- allocated_quantity
- inventory_before
- inventory_after
- ageing_before
- ageing_after
- ageing_consumed_quantity
- movement_timestamp
- reason_code
- movement_type
- remarks

### OrderLine

- order_id
- line_id
- order_creation_timestamp
- order_type
- material_code
- dealer_code
- parent_rdc
- requested_quantity
- remaining_quantity
- is_credit_blocked
- colour_code
- raw_order_type
- dealer_norms

### Route

- source_location
- destination_location
- transport_mode
- standard_sla_days
- pickup_buffer_hours
- drop_buffer_hours
- transport_cost
- connectivity_available
- applicable_order_types
- effective_start_datetime
- effective_end_datetime
- route_type

### SafetyStockEvaluation

- norms
- norms_found
- safety_stock_exempt_due_to_norms
- mad
- mad_default_used
- rlt_days
- calculated_safety_stock
- applied_safety_stock
- safety_stock_protected
- safety_stock_policy

### TransportEligibilityResult

- eligible
- reason_codes

### CandidateScoreBreakdown

- candidate_location
- candidate_source_type
- final_score
- ageing_component
- sla_component
- rlt_component
- cost_component
- source_priority_component
- weighted_components
- scoring_pool

### SourceSelectionResult

- decision
- selected_candidate
- allocated_quantity
- remaining_quantity
- reason_codes

### GitReservationMovement

- git_movement_id
- order_id
- line_id
- order_category
- material_code
- destination_location
- source_location
- asn_number
- dispatch_datetime
- expected_arrival_datetime
- inbound_rlt_days
- arrival_days_from_decision
- git_quantity_before
- reserved_quantity
- git_quantity_after
- movement_timestamp
- movement_type
- reason_code
- remarks

### AvailableGitShipment

- material_code
- destination_location
- source_location
- asn_number
- dispatch_datetime
- expected_arrival_datetime
- inbound_rlt_days
- available_quantity

### PushWorkflowResult

- selection_result
- evaluated_candidates
- inventory_movement
- inventory_movements
- source_allocations
- moq_allocation_result

### ReplenishmentWorkflowResult

- selection_result
- evaluated_candidates
- inventory_movement
- inventory_movements
- source_allocations
- moq_allocation_result

### VORWorkflowResult

- selection_result
- evaluated_candidates
- inventory_movement
- inventory_movements
- source_allocations
- moq_allocation_result


## Workflows

### __init__.py


### push.py

- add_sla_data_not_found_to_selection_if_needed()
- select_push_source_by_weighted_score()
- select_parent_full_fill_for_push()
- build_single_candidate_selection_result_for_push()
- can_fulfil_push_from_combined_ageing()
- get_push_ageing_candidates_for_multi_source()
- allocate_push_multi_source_ageing()
- get_ageing_allocatable_quantity()
- select_single_source_ageing_full_fill_for_push()
- build_single_source_ageing_selection_result_for_push()
- process_push_order()

### replenishment.py

- is_non_auto_customer()
- add_sla_data_not_found_to_selection_if_needed()
- select_non_auto_customer_vepdc_only()
- select_replenishment_parent_then_weighted_score()
- select_replenishment_parent_then_sequential_rules()
- select_replenishment_source_by_strategy()
- normalize_colour_code()
- is_parent_only_replenishment_colour()
- is_rerouting_allowed_replenishment_colour()
- select_replenishment_parent_only()
- append_reason_code_once()
- process_replenishment_order()

### vor.py

- is_non_auto_customer()
- calculate_vor_effective_requested_quantity()
- select_parent_full_fill_for_vor()
- build_vor_selection_result()
- enrich_vor_acc_candidates_with_rlt()
- _safe_sla_days()
- _safe_ageing_quantity()
- _safe_eligible_quantity()
- _safe_rlt_days()
- _safe_transport_cost()
- select_vor_acc_rerouting_candidate()
- select_vor_source()
- select_non_auto_customer_vepdc_only_for_vor()
- adjust_vor_selection_result_to_original_quantity()
- process_vor_order()


## Scoring Configuration

## replenishment_moq_scoring

```yaml
weights:
  sla: 0.3
  ageing: 0.25
  rlt: 0.2
  eligible_quantity: 0.15
  cost: 0.1
missing_values:
  sla: 5
  rlt: 5
  cost: 999999999
```

## zfmo_replenishment_moq_scoring

```yaml
weights:
  sla: 0.8
  ageing: 0.05
  rlt: 0.05
  eligible_quantity: 0.1
  cost: 0.0
missing_values:
  sla: 5
  rlt: 5
  cost: 999999999
```

## zmso_colour_16_moq_scoring

```yaml
weights:
  sla: 0.8
  ageing: 0.1
  rlt: 0.05
  eligible_quantity: 0.05
  cost: 0.0
missing_values:
  sla: 5
  rlt: 5
  cost: 999999999
```

## push_selection

```yaml
strategy: WEIGHTED_SCORING
mandatory_rules:
  single_source_only: true
  no_split: true
  credit_block_check: true
  non_auto_customer_vepdc_only: true
weighted_scoring:
  enabled: true
  quantity_rule:
    full_fill_first: true
    if_no_full_fill_select_max_quantity_first: true
    quantity_is_not_weighted_when_full_fill_available: true
  weights:
    ageing: 0.45
    sla: 0.2
    rlt: 0.15
    cost: 0.1
    source_priority: 0.1
  scoring_direction:
    ageing: higher_is_better
    sla: lower_is_better
    rlt: lower_is_better
    cost: lower_is_better
    source_priority: lower_is_better
  rlt_defaults:
    VEPDC: 0
    missing_rlt: 9999
  source_priority:
    PARENT_RDC: 1
    CLUSTER_RDC: 2
    PAN_INDIA_RDC: 2
    VEPDC: 3
    PARENT_GIT: 4
  score_round_digits: 6
```


## Execution Defaults

```yaml
missing_sla_days: 5
missing_rlt_days: 5
missing_route_transport_mode: SURFACE
missing_route_transport_cost: 999999999
```