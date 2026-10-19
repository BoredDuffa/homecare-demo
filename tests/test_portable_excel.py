from io import BytesIO
from openpyxl import load_workbook
from examples import examples
from workbook_io import export_workbook,parse_workbook


def test_excel_export_needs_no_node_or_local_runtime(tmp_path,monkeypatch):
    monkeypatch.setenv('PATH','')
    p=examples()[0]['data'];p['clients'][0]['name']='=HYPERLINK("https://example.invalid","literal")'
    target=tmp_path/'framework.xlsx'
    body=export_workbook(p,template=True,output_path=target)
    assert target.read_bytes()==body
    book=load_workbook(BytesIO(body),read_only=True,data_only=False)
    assert book['Clients']['B2'].value==p['clients'][0]['name']
    assert book['Clients']['B2'].data_type=='s'
    assert book['Availability']['C2'].value.hour==8
    book.close()
    imported=parse_workbook(body)
    assert not imported['issues'] and imported['counts']['visits']==56
    assert imported['draft']['clients'][0]['name']==p['clients'][0]['name']
