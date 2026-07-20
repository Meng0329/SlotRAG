import pytest

from slotrag.models import BindingRow, JoinSpec, Slot, SlotPlan


def test_slot_query_substitutes_bound_variables():
    slot = Slot(id="S1", predicate="Founded", arguments=["?person", "?company"])
    assert slot.query_text({"person": "Ada Lovelace"}) == "Founded Ada Lovelace ?company"


def test_join_spec_accepts_document_pair_form():
    join = JoinSpec.model_validate(["S1.person", "S2.person"])
    assert join.left_slot == "S1"
    assert join.right_field == "person"


def test_slot_plan_rejects_unknown_join_slot():
    with pytest.raises(ValueError):
        SlotPlan.model_validate({
            "slots": [{"id": "S1", "predicate": "P", "arguments": ["?x"]}],
            "joins": [["S1.x", "S2.x"]],
            "outputs": ["?x"],
        })


def test_slot_plan_rejects_disconnected_join_graph():
    with pytest.raises(ValueError, match="connected"):
        SlotPlan.model_validate({
            "slots": [
                {"id": "S1", "predicate": "P", "arguments": ["?x"]},
                {"id": "S2", "predicate": "Q", "arguments": ["?x"]},
                {"id": "S3", "predicate": "R", "arguments": ["?z"]},
            ],
            "joins": [["S1.x", "S2.x"]],
            "outputs": ["?x"],
        })


def test_slot_plan_rejects_join_field_not_declared_as_variable():
    with pytest.raises(ValueError, match="field"):
        SlotPlan.model_validate({
            "slots": [
                {"id": "S1", "predicate": "P", "arguments": ["?x", "constant"]},
                {"id": "S2", "predicate": "Q", "arguments": ["?y"]},
            ],
            "joins": [["S1.constant", "S2.y"]],
            "outputs": ["?x"],
        })


def test_binding_row_requires_source_span():
    with pytest.raises(ValueError):
        BindingRow.model_validate({"slot_id": "S1", "bindings": {"x": "y"}, "source_id": "doc"})
