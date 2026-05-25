import pytest
import pandas as pd
import requests
from unittest.mock import patch
from generate_pdf_report import (
    ReportGenerator,
    Config,
    COLUMNS_BY_ID,
    DEFAULT_COLUMNS,
    _validate_columns,
    _choose_orientation,
    _estimate_table_width,
    PORTRAIT_WIDTH_BUDGET,
    LANDSCAPE_WIDTH_BUDGET,
)


@pytest.fixture
def config():
    return Config(
        evcc_url="http://mock-evcc",
        evcc_password="",
        smtp_server="smtp.mock",
        smtp_port=587,
        sender_email="sender@mock.com",
        sender_password="pass",
        recipient_email="recipient@mock.com",
        sender_name="Sender",
        sender_street="Street",
        sender_city="City",
        locale="en_US.UTF-8",
    )


@pytest.fixture
def generator(config):
    return ReportGenerator(config)


def _session(loadpoint_id=1, vehicle='Tesla', loadpoint='Garage', energy=50.5,
             price=15.0, odometer=12345, meter_start=1000.0, meter_stop=1050.5):
    return {
        'id': loadpoint_id,
        'created': '2023-10-01T10:00:00Z',
        'finished': '2023-10-01T12:00:00Z',
        'loadpoint': loadpoint,
        'vehicle': vehicle,
        'chargedEnergy': energy,
        'price': price,
        'odometer': odometer,
        'meterStart': meter_start,
        'meterStop': meter_stop,
    }


def test_process_data_empty(generator):
    df = generator.process_data([])
    assert df.empty


def test_process_data_valid(generator):
    df = generator.process_data([_session()])
    assert not df.empty
    assert 'start_time' in df.columns
    assert 'duration' in df.columns
    assert df.iloc[0]['duration'] == "2h 0m"
    assert df.iloc[0]['energy'] == 50.5
    assert df.iloc[0]['odometer'] == 12345
    assert df.iloc[0]['meter_start'] == 1000.0
    assert df.iloc[0]['meter_end'] == 1050.5
    assert df.iloc[0]['loadpoint_idx'] == 1


def test_process_data_missing_optional_fields(generator):
    # The raw response is missing odometer/meterStart/meterStop entirely.
    minimal = {
        'id': 1,
        'created': '2023-10-01T10:00:00Z',
        'finished': '2023-10-01T12:00:00Z',
        'loadpoint': 'Garage',
        'vehicle': 'Tesla',
        'chargedEnergy': 50.5,
        'price': 15.0,
    }
    df = generator.process_data([minimal])
    assert not df.empty
    assert pd.isna(df.iloc[0]['odometer'])
    assert pd.isna(df.iloc[0]['meter_start'])
    assert pd.isna(df.iloc[0]['meter_end'])


def test_loadpoint_idx_from_api_id(generator):
    # API gives loadpoint index via the `id` field — verify it's used directly,
    # not derived from the loadpoint name.
    df = generator.process_data([
        _session(loadpoint_id=2, loadpoint='Carport'),
        _session(loadpoint_id=1, loadpoint='Garage'),
    ])
    assert df.iloc[0]['loadpoint_idx'] == 2
    assert df.iloc[1]['loadpoint_idx'] == 1


def test_filter_vehicle(generator):
    generator.config.filter_vehicles = ['Tesla']
    df = generator.process_data([
        _session(vehicle='Tesla'),
        _session(vehicle='BMW'),
    ])
    df = generator._apply_filters(df)
    assert len(df) == 1
    assert df.iloc[0]['vehicle'] == 'Tesla'


def test_filter_loadpoint(generator):
    generator.config.filter_loadpoints = ['Garage']
    df = generator.process_data([
        _session(loadpoint='Garage'),
        _session(loadpoint='Carport'),
    ])
    df = generator._apply_filters(df)
    assert len(df) == 1
    assert df.iloc[0]['loadpoint'] == 'Garage'


def test_filter_vehicle_name_with_spaces(generator):
    generator.config.filter_vehicles = ['Nissan Leaf']
    df = generator.process_data([
        _session(vehicle='Nissan Leaf'),
        _session(vehicle='Tesla Model 3'),
    ])
    df = generator._apply_filters(df)
    assert len(df) == 1
    assert df.iloc[0]['vehicle'] == 'Nissan Leaf'


def test_filter_empty_whitelist_keeps_all(generator):
    df = generator.process_data([
        _session(vehicle='Tesla'),
        _session(vehicle='BMW'),
    ])
    df = generator._apply_filters(df)
    assert len(df) == 2


def test_columns_subset_in_format(generator):
    generator.config.columns = ['start_time', 'energy']
    df = generator.process_data([_session()])
    selected = generator._resolve_selected_columns()
    formatted = generator._format_dataframe(df, selected)
    assert list(formatted.columns) == ['start_time', 'energy']


def test_format_includes_new_columns(generator):
    generator.config.columns = ['odometer', 'meter_start', 'meter_end', 'loadpoint_idx']
    df = generator.process_data([_session()])
    selected = generator._resolve_selected_columns()
    formatted = generator._format_dataframe(df, selected)
    assert formatted.iloc[0]['odometer'] == '12345'
    assert formatted.iloc[0]['meter_start']  # non-empty formatted string
    assert formatted.iloc[0]['meter_end']
    assert formatted.iloc[0]['loadpoint_idx'] == '1'


def test_empty_filter_result_still_renders(generator, tmp_path):
    generator.config.output_folder = str(tmp_path)
    generator.config.filter_vehicles = ['NoSuchVehicle']
    df = generator.process_data([_session(vehicle='Tesla')])
    df = generator._apply_filters(df)
    assert df.empty
    with patch('generate_pdf_report.HTML') as mock_html:
        mock_html.return_value.write_pdf.return_value = None
        pdf_path, pdf_filename = generator.generate_pdf(df, 2023, 10)
    assert pdf_path is not None
    assert pdf_filename == 'ChargingCostSummary_2023-10.pdf'


def test_orientation_default_columns_is_portrait():
    assert _choose_orientation(list(DEFAULT_COLUMNS)) == 'portrait'
    assert _estimate_table_width(DEFAULT_COLUMNS) <= PORTRAIT_WIDTH_BUDGET


def test_orientation_many_columns_switches_to_landscape():
    # All columns selected — wider than portrait, should switch to landscape.
    all_cols = list(COLUMNS_BY_ID.keys())
    width = _estimate_table_width(all_cols)
    assert width > PORTRAIT_WIDTH_BUDGET
    assert _choose_orientation(all_cols) == 'landscape'


def test_orientation_huge_selection_warns_but_still_landscape(caplog):
    # Pad the column list past the landscape budget by repeating wide columns.
    # We can't actually duplicate IDs through real config (validation would
    # reject most cases), but the helper accepts any list of IDs so this tests
    # the warning path directly.
    wide_cols = ['start_time', 'end_time', 'meter_start', 'meter_end',
                 'odometer', 'loadpoint', 'vehicle', 'energy', 'duration',
                 'price', 'loadpoint_idx']
    # Force a synthetic width over the landscape budget by repeating entries.
    overflow = wide_cols + ['start_time', 'end_time', 'meter_start', 'meter_end']
    assert _estimate_table_width(overflow) > LANDSCAPE_WIDTH_BUDGET
    with caplog.at_level('WARNING'):
        assert _choose_orientation(overflow) == 'landscape'
    assert any('exceeds' in rec.message for rec in caplog.records)


def test_unknown_column_id_exits():
    with pytest.raises(SystemExit) as exc_info:
        _validate_columns(['start_time', 'nonsense'])
    assert exc_info.value.code == 2


def test_known_column_ids_pass():
    _validate_columns(list(DEFAULT_COLUMNS))  # should not raise


def test_default_columns_all_known():
    for cid in DEFAULT_COLUMNS:
        assert cid in COLUMNS_BY_ID


def test_fetch_data_success_wrapped(generator):
    # Documented evcc shape: {"result": [...]}.
    with patch('requests.Session.get') as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {'result': [{'some': 'data'}]}

        data = generator.fetch_data(2023, 10)
        assert data == [{'some': 'data'}]


def test_fetch_data_success_bare_list(generator):
    # Tolerate older shape that returned a bare array.
    with patch('requests.Session.get') as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [{'some': 'data'}]

        data = generator.fetch_data(2023, 10)
        assert data == [{'some': 'data'}]


def test_fetch_data_failure(generator):
    with patch('requests.Session.get') as mock_get:
        mock_get.side_effect = requests.exceptions.RequestException("Connection error")
        data = generator.fetch_data(2023, 10)
        assert data is None


def test_template_file_selection(config):
    config.locale = 'de_DE.UTF-8'
    gen = ReportGenerator(config)
    assert gen.template_file == 'template_de.html'

    config.locale = 'en_US.UTF-8'
    gen = ReportGenerator(config)
    assert gen.template_file == 'template_en.html'


def test_run_manual_date(generator):
    with patch.object(generator, 'fetch_data') as mock_fetch, \
         patch.object(generator, 'process_data') as mock_process, \
         patch.object(generator, 'generate_pdf') as mock_gen_pdf, \
         patch.object(generator, 'send_email'):

        mock_fetch.return_value = [{'data': 'test'}]
        mock_process.return_value = pd.DataFrame([{'data': 'test'}])
        mock_gen_pdf.return_value = ('path', 'file')

        generator.run(year=2022, month=5)

        mock_fetch.assert_called_once_with(2022, 5)
