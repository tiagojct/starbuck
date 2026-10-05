from starbuck.ids import containment, detect, find_ids, norm_doi, same_name, title_similarity


def test_doi_forms():
    assert norm_doi("https://doi.org/10.1183/09031936.00080312") == "10.1183/09031936.00080312"
    assert norm_doi("doi: 10.1183/09031936.00080312.") == "10.1183/09031936.00080312"
    assert norm_doi("(doi:10.1183/09031936.00080312)") == "10.1183/09031936.00080312"
    assert norm_doi("https://dx.doi.org/10.1183%2F09031936.00080312") == "10.1183/09031936.00080312"
    # balanced parentheses belong to the DOI; an unbalanced closing one does not
    assert norm_doi("10.1016/S0140-6736(97)11096-0") == "10.1016/s0140-6736(97)11096-0"
    assert norm_doi("(see 10.1016/S0140-6736(97)11096-0).") == "10.1016/s0140-6736(97)11096-0"
    assert norm_doi("<https://doi.org/10.1000/abc>") == "10.1000/abc"
    assert norm_doi("no doi here") is None


def test_detect():
    assert detect("pmid:123") == ("pmid", "123")
    assert detect("123456") == ("pmid", "123456")
    assert detect("https://pubmed.ncbi.nlm.nih.gov/22743675/") == ("pmid", "22743675")
    assert detect("arXiv:1706.03762v5") == ("arxiv", "1706.03762")
    assert detect("https://arxiv.org/abs/2408.03314") == ("arxiv", "2408.03314")
    assert detect("1706.03762") == ("arxiv", "1706.03762")
    assert detect("PMC3786581") == ("pmcid", "PMC3786581")
    assert detect("isbn:0-19-957777-4")[0] == "isbn"
    assert detect("10.1000/x") == ("doi", "10.1000/x")
    assert detect("hello") is None


def test_find_ids_in_free_text():
    ids = find_ids("Quanjer PH, et al. Eur Respir J 2012;40:1324-43. doi:10.1183/09031936.00080312. "
                   "PMID: 22743675. https://example.org/page")
    assert ids["doi"] == "10.1183/09031936.00080312"
    assert ids["pmid"] == "22743675"
    assert ids["year"] == "2012"
    assert ids["url"] == "https://example.org/page"
    # a year inside a DOI or page range is not the publication year
    assert "year" not in find_ids("https://doi.org/10.1000/2019.x")


def test_similarity_and_names():
    assert title_similarity("Standardisation of spirometry", "Standardisation of Spirometry.") == 1.0
    assert title_similarity("Multi-ethnic reference values for spirometry: the GLI 2012 equations",
                            "Multi-ethnic reference values for spirometry") >= 0.9
    assert title_similarity("Standardisation of spirometry", "Ileal-lymphoid-nodular hyperplasia") < 0.6
    assert containment("Standardisation of spirometry", "Miller MR. Standardisation of spirometry. 2005") == 1.0
    assert same_name("Fonsêca", "Fonseca")
    assert same_name("da Silva", "Silva")
    assert not same_name("Silva", "Souza")


def test_flag_prefixes_ignored():
    t = "Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive developmental disorder in children"
    assert title_similarity(t, "RETRACTED: " + t) == 1.0
    assert containment("RETRACTED: " + t, "Wakefield AJ. " + t + ". Lancet 1998") == 1.0
