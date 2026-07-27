from benchmark.download_datasets import classify_drop_operation


def test_drop_operation_classifier_separates_arithmetic_from_counting():
    assert classify_drop_operation("How many years before X did Y happen?") == "arithmetic"
    assert classify_drop_operation("How many people attended?") == "counting"
    assert classify_drop_operation("List all the names.") == "listing"
