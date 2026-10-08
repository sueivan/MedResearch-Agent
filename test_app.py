from app import clean_doi, dedup, app
from fastapi.testclient import TestClient

def test_doi_normalization():
    assert clean_doi('https://doi.org/10.1000/ABC')=='10.1000/abc'

def test_dedup_cross_database():
    items=[{'source':'PubMed','pmid':'123','doi':'10.1/ABC','title':'Trial A'},{'source':'Europe PMC','pmid':'123','doi':'10.1/abc','title':'Trial A'},{'source':'ClinicalTrials.gov','nct_id':'NCT123','title':'Other Trial'}]
    assert len(dedup(items))==2

def test_invalid_source():
    r=TestClient(app).get('/api/search',params={'q':'test','sources':'bad'})
    assert r.status_code==400

def test_home():
    r=TestClient(app).get('/')
    assert r.status_code==200 and 'MedResearch Agent' in r.text
