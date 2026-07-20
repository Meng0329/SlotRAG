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


def test_binding_row_requires_source_span():
    with pytest.raises(ValueError):
        BindingRow.model_validate({"slot_id": "S1", "bindings": {"x": "y"}, "source_id": "doc"})
