"""Unit tests for dbx.report.markdown – table rendering and report assembly."""

import pytest
from dbx.report.markdown import ReportBuilder, err_block, md_table, section


class TestMdTable:
    def test_basic_table(self):
        rows = [{"a": 1, "b": "hello"}, {"a": 2, "b": "world"}]
        result = md_table(rows, ["a", "b"])
        lines = result.splitlines()
        assert lines[0] == "| a | b |"
        assert lines[1] == "| --- | --- |"
        assert "1" in lines[2]
        assert "hello" in lines[2]
        assert "world" in lines[3]

    def test_empty_rows(self):
        result = md_table([], ["a", "b"])
        assert result == "*No data.*"

    def test_missing_key_renders_empty(self):
        rows = [{"a": "val"}]
        result = md_table(rows, ["a", "b"])
        assert "val" in result
        # 'b' column should be empty
        lines = result.splitlines()
        assert lines[2].count("|") >= 3

    def test_pipe_in_value_is_escaped(self):
        rows = [{"col": "foo|bar"}]
        result = md_table(rows, ["col"])
        assert "foo\\|bar" in result

    def test_none_value_renders_empty(self):
        rows = [{"col": None}]
        result = md_table(rows, ["col"])
        assert "None" not in result

    def test_newline_in_value_replaced(self):
        rows = [{"col": "line1\nline2"}]
        result = md_table(rows, ["col"])
        assert "\n" not in result.splitlines()[2]

    def test_column_order(self):
        rows = [{"z": "last", "a": "first"}]
        result = md_table(rows, ["a", "z"])
        lines = result.splitlines()
        assert lines[0].index("a") < lines[0].index("z")


class TestErrBlock:
    def test_contains_title(self):
        result = err_block("Something broke", "details here")
        assert "Something broke" in result

    def test_contains_detail(self):
        result = err_block("Title", "detail text")
        assert "detail text" in result

    def test_is_blockquote(self):
        result = err_block("T", "D")
        assert result.startswith(">")


class TestSection:
    def test_heading_level(self):
        result = section("My Section", 2, "body text")
        assert result.startswith("## My Section")

    def test_body_included(self):
        result = section("Title", 3, "the body")
        assert "the body" in result


class TestReportBuilder:
    def test_title_in_output(self):
        rb = ReportBuilder("My Report")
        rb.add("Section A", "Content A")
        doc = rb.build()
        assert "# My Report" in doc

    def test_sections_present(self):
        rb = ReportBuilder()
        rb.add("Alpha", "alpha content")
        rb.add("Beta", "beta content")
        doc = rb.build()
        assert "Alpha" in doc
        assert "alpha content" in doc
        assert "Beta" in doc
        assert "beta content" in doc

    def test_toc_generated(self):
        rb = ReportBuilder()
        rb.add("Alpha", "content")
        rb.add("Beta", "more content")
        doc = rb.build()
        assert "Table of Contents" in doc
        assert "Alpha" in doc
        assert "Beta" in doc

    def test_build_returns_string(self):
        rb = ReportBuilder()
        assert isinstance(rb.build(), str)

    def test_empty_builder(self):
        rb = ReportBuilder()
        doc = rb.build()
        assert "# " in doc

    def test_chaining(self):
        rb = ReportBuilder()
        result = rb.add("A", "content A").add("B", "content B")
        assert result is rb
