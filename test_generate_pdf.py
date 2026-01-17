import pytest
import pandas as pd
import requests
from unittest.mock import patch
from generate_pdf_report import ReportGenerator, Config


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
        locale="en_US.UTF-8"
    )


@pytest.fixture
def generator(config):
    return ReportGenerator(config)


def test_process_data_empty(generator):
    df = generator.process_data([])
    assert df.empty


def test_process_data_valid(generator):
    data = [{
        'created': '2023-10-01T10:00:00Z',
        'finished': '2023-10-01T12:00:00Z',
        'loadpoint': 'Garage',
        'vehicle': 'Tesla',
        'chargedEnergy': 50.5,
        'price': 15.0
    }]
    df = generator.process_data(data)
    assert not df.empty
    assert 'Start Time' in df.columns
    assert 'Charging Duration' in df.columns
    assert df.iloc[0]['Charging Duration'] == "2h 0m"
    assert df.iloc[0]['Energy (kWh)'] == 50.5


def test_fetch_data_success(generator):
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