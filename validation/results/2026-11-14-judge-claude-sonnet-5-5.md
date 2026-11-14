# Starbuck level 4 judge, independent set: 2026-11-14T22:37:17+00:00

Judge: claude-sonnet-5-5; Starbuck 0.4.0; mode: live; cases: 100 (judge_cases.jsonl, SHA-256 535914c55a2f).

- Agreement, strict: 73/100 = 73.0% (63.6 to 80.7)
- Agreement, lenient (cannot_assess accepted for SciFact NOINFO and PubMedQA maybe): 75/100 = 75.0% (65.7 to 82.5)
- scifact: strict 48/60 = 80.0% (68.2 to 88.2); lenient 50/60 = 83.3% (72.0 to 90.7)
- pubmedqa: strict 25/40 = 62.5% (47.0 to 75.8); lenient 25/40 = 62.5% (47.0 to 75.8)
- Quotes rejected: 1/100 = 1.0% (0.2 to 5.4) of the cases the judge answered
- Supported where the label expects another verdict: 4

## Confusion matrix

| Dataset label | supported | partly_supported | not_supported | cannot_assess |
|---|---|---|---|---|
| scifact SUPPORT | 14 | 2 | 3 | 1 |
| scifact CONTRADICT | 1 | 1 | 18 | 0 |
| scifact NOINFO | 0 | 2 | 16 | 2 |
| pubmedqa yes | 10 | 3 | 2 | 0 |
| pubmedqa no | 0 | 2 | 13 | 0 |
| pubmedqa maybe | 3 | 2 | 5 | 0 |

## Cases that differ (strict)

| Case | Label | Expected | Verdict | Reason |
|---|---|---|---|---|
| sf415-6309659 | scifact SUPPORT | supported | not_supported | The abstract reports that reproductive period length interacts with APOE4 status in women, but it never compares APOE4 carriers with noncarriers on baseline dementia risk, so it does not state that female carriers have increased dementia risk. |
| sf431-28937856 | scifact SUPPORT | supported | not_supported | The abstract covers FOXO3 regulation by SIRT1 under oxidative stress but does not say that FoxO3a activation in neuronal death is mediated by ROS. |
| sf593-19675911 | scifact SUPPORT | supported | cannot_assess | The quotation does not appear word for word in the source text. Rejected verdict: not_supported. The source reports that heart failure incidence did not change over time in women, contradicting a 10% decrease since 1979. |
| sf936-5483793 | scifact SUPPORT | supported | partly_supported | The abstract links peroxynitrite production to TCR-CD8 nitration, but it does not state that peroxynitrite is required, for example by showing that blocking it prevents nitration. |
| sf1019-11603066 | scifact SUPPORT | supported | not_supported | The abstract attributes specificity to structural recognition determinants (e.g. a methionine finger) and does not claim that rapid phosphotransfer rates govern fidelity. |
| sf1132-33499189 | scifact SUPPORT | supported | partly_supported | The abstract supports that TCR-CD3 clustering is needed for triggering and activation, but it does not mention microdomains or the immunologic synapse, so the claim goes beyond it. |
| sf183-12827098 | scifact CONTRADICT | not_supported | partly_supported | The abstract shows that donor bone marrow progenitors can give rise to macrophages after transplantation, but its main claim is that tissue macrophages are maintained independently of monocytes in the steady state, so it only weakly supports a bone marrow contribution to adult macrophage compartments. |
| sf1088-37549932 | scifact CONTRADICT | not_supported | supported | The study shows that eliminating (silencing) BCL-2 in a mouse leukemia model kills the tumor cells and prolongs survival, so BCL-2 is needed for tumor maintenance; the sentence's claim about progression is slightly broader but is consistent with this. |
| sf575-10300888 | scifact NOINFO | not_supported | cannot_assess | The abstract does not mention aneuploidy, and the full text would be needed to judge whether whole-chromosome aneuploidy is uncommon in domesticated strains. |
| sf659-1215116 | scifact NOINFO | not_supported | cannot_assess | The abstract passages mention lymphatic filariasis control but do not mention ivermectin or its use as treatment, and the full text (likely with the drug details) is not provided. |
| sf1213-14407673 | scifact NOINFO | not_supported | partly_supported | The study shows that loss of myeloid KLF2 worsens atherosclerosis, with more adhesive macrophages and neutrophils, which fits harmful myeloid cell activity in an inflammatory disease. It does not directly address deregulated, prolonged monocyte activation, and it found macrophage activation itself was unchanged. |
| sf1279-11335781 | scifact NOINFO | not_supported | partly_supported | The abstract says autoimmunity and immunotoxicity arise with cancer immunotherapy in general, but it never names co-IR (checkpoint) blockade specifically. |
| pq10173769 | pubmedqa yes | supported | not_supported | The passages state the study question and correlations but give no conclusion that the Barthel index alone is adequate; the correlations, some weak, do not clearly establish a 'yes'. |
| pq14745753 | pubmedqa yes | supported | partly_supported | The abstract shows comparable overall image quality with half-dose, but SNR and CNR were lower in the 0.5 mL/second groups and no explicit conclusion of sufficiency is stated. |
| pq18575014 | pubmedqa yes | supported | partly_supported | The abstract shows marked familial aggregation of NP, which suggests a hereditary factor, but the provided passages do not state an explicit conclusion about an inheritance pattern. |
| pq27896825 | pubmedqa yes | supported | partly_supported | The abstract shows a subset (22%) of low-risk children did well, which hints at lobectomy being adequate, but the passages give no explicit conclusion answering "yes" and the study was retrospective with short follow-up. |
| pq9722752 | pubmedqa yes | supported | not_supported | The study is a single-arm series with no comparison group, so it cannot show that bone anchor fixation improves outcome relative to standard percutaneous suspension, and its 68% success rate with notable complications does not support a clear 'yes'. |
| pq19575307 | pubmedqa no | not_supported | partly_supported | The abstract shows higher GFR (hyperfiltration) in women with four or more parities, but the passages do not show that it damages the kidney, so the "yes" answer is only partly backed. |
| pq26852225 | pubmedqa no | not_supported | partly_supported | The abstract shows that adjustment changed some findings (sex lost significance, exercise became significant), but it describes only subtle differences in coefficients and gives no explicit conclusion that adjustment is necessary. |
| pq11296674 | pubmedqa maybe | partly_supported | not_supported | The abstract reports an uncommon association of prostate and lung cancer and says nothing that answers whether prostatic syndrome and pleural effusion are different diseases. |
| pq16392897 | pubmedqa maybe | partly_supported | supported | The abstract reports a strong correlation between two labs using different homebrew assays, which supports a 'yes' answer. |
| pq16968876 | pubmedqa maybe | partly_supported | supported | The abstract shows that self-reported HRQOL items (pain and dysphagia) were independent prognostic factors for survival in NSCLC patients, so the answer is yes. |
| pq17179167 | pubmedqa maybe | partly_supported | not_supported | Only 4 of 90 pterygia were HPV-positive (all ISH negative) and controls were negative, so the data do not establish HPV as a risk factor; the abstract does not conclude 'yes'. |
| pq17279467 | pubmedqa maybe | partly_supported | not_supported | This case report shows BMD dropped sharply and stress fractures occurred after stopping treatment, so it does not answer "yes" and points toward the opposite. |
| pq18800356 | pubmedqa maybe | partly_supported | not_supported | The abstract shows only 57% of RA patients passed all the physical tests, so a flat "yes" overstates it; the data suggest many RA patients are not physically able to participate. |
| pq18802997 | pubmedqa maybe | partly_supported | supported | The study found positive calprotectin significantly predicted relapse in UC and in colonic CD, though not in all CD, so a general 'yes' is largely backed. |
| pq20197761 | pubmedqa maybe | partly_supported | not_supported | The study measured provider beliefs, finding experts rarely (8%) and nonexperts mostly (72%) endorse IBS as a diagnosis of exclusion, and it did not conclude that IBS is a diagnosis of exclusion; guidelines say it is not. |
