#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copyright (C) 2016
@authors: Derek Pisner
"""
import pandas as pd
import os
import re
import glob
import numpy as np
import itertools
import warnings
from collections import OrderedDict

warnings.simplefilter("ignore")


def get_ensembles_embedding(modality, alg, base_dir):
    if alg == "OMNI":
        ensembles_pre = list(
            set(
                [
                    "rsn-"
                    + i.split('rsn-')[1].split("_")[0]
                    + "_res-"
                    + i.split('res-')[1].split("/")[0]
                    + "_"
                    + os.path.basename(i).split(modality + "_")[1].replace(".npy", "")
                    for i in glob.glob(
                        f"{base_dir}/embeddings_all_{modality}/*/*/*/*{alg}*.npy"
                    )
                ]
            )
        )
        ensembles = []
        for i in ensembles_pre:
            if '_thrtype' in i:
                ensembles.append(i.split('_thrtype')[0])
            else:
                ensembles.append(i)
    elif alg == "ASE":
        ensembles_pre = list(
            set(
                [
                    "rsn-"
                    + i.split('rsn-')[1].split("_")[0]
                    + "_res-"
                    + i.split('res-')[1].split("/")[0]
                    + "_"
                    + os.path.basename(i).split(modality + "_")[1].replace(".npy", "")
                    for i in glob.glob(
                        f"{base_dir}/embeddings_all_{modality}/*/*/*/*{alg}*.npy")
                ]
            )
        )
        ensembles = []
        for i in ensembles_pre:
            if '_thrtype' in i:
                ensembles.append(i.split('_thrtype')[0])
            else:
                ensembles.append(i)
    else:
        ensembles = None
    return ensembles


def get_ensembles_top(modality, thr_type, base_dir, drop_thr=0.50):
    topology_file = f"{base_dir}/all_subs_neat_{modality}.csv"
    if os.path.isfile(topology_file):
        df_top = pd.read_csv(topology_file)
        if "Unnamed: 0" in df_top.columns:
            df_top.drop(df_top.filter(regex="Unnamed: 0"), axis=1,
                         inplace=True)
        df_top = df_top.dropna(subset=["id"])
        df_top = df_top.rename(
            columns=lambda x: re.sub("_partcorr", "_model-partcorr", x)
        )
        df_top = df_top.rename(columns=lambda x: re.sub("_corr", "_model-corr", x))
        df_top = df_top.rename(columns=lambda x: re.sub("_cov", "_model-cov", x))
        df_top = df_top.rename(columns=lambda x: re.sub("_sfm", "_model-sfm", x))
        df_top = df_top.rename(columns=lambda x: re.sub("_csa", "_model-csa", x))
        df_top = df_top.rename(columns=lambda x: re.sub("_tensor", "_model-tensor", x))
        df_top = df_top.rename(columns=lambda x: re.sub("_csd", "_model-csd", x))
        df_top = df_top.rename(
            columns=lambda x: re.sub("thrtype-PROP", "thrtype-MST", x))
        # df_top = df_top.dropna(how='all')
        # df_top = df_top.dropna(axis='columns',
        #                        thresh=drop_thr * len(df_top)
        #                        )
        if not df_top.empty and len(df_top.columns) > 1:
            [df_top, ensembles] = graph_theory_prep(df_top, thr_type)
            #print(df_top)
            ensembles = [i for i in ensembles if i != "id"]
        else:
            ensembles = None
            df_top = None
    else:
        ensembles = None
        df_top = None
    return ensembles, df_top


def make_feature_space_dict(
    base_dir,
    ml_dfs,
    df,
    target_modality,
    subject_dict,
    ses,
    modality_grids,
    target_embedding_type,
    mets=None,
):
    from joblib import Parallel, delayed
    import tempfile
    import gc

    cache_dir = tempfile.mkdtemp()

    if target_modality not in ml_dfs.keys():
        ml_dfs[target_modality] = {}
    if target_embedding_type not in ml_dfs[target_modality].keys():
        ml_dfs[target_modality][target_embedding_type] = {}
    grid_params = list(set(modality_grids[target_modality]))

    grid_params_mod = []
    if target_modality == "func":
        for comb in grid_params:
            try:
                extract, hpass, model, res, atlas, smooth = comb
                grid_params_mod.append((extract, hpass, model, res, atlas, str(smooth)))
            except:
                try:
                    extract, hpass, model, res, atlas = comb
                    smooth = "0"
                    grid_params_mod.append((extract, hpass, model, res, atlas, str(smooth)))
                except:
                    print(f"Failed to parse recipe: {comb}")

    elif target_modality == "dwi":
        for comb in grid_params:
            try:
                directget, minlength, model, res, atlas, tol = comb
                grid_params_mod.append((directget, minlength, model, res, atlas, tol))
            except:
                print(f"Failed to parse recipe: {comb}")

    par_dict = subject_dict.copy()

    with Parallel(
        n_jobs=-1, backend='loky', verbose=10, temp_folder=cache_dir
    ) as parallel:
        outs = parallel(
            delayed(create_feature_space)(
                base_dir,
                df,
                grid_param,
                par_dict,
                ses,
                target_modality,
                target_embedding_type,
                mets
            )
            for grid_param in grid_params_mod
        )
    for fs, grid_param in outs:
        ml_dfs[target_modality][target_embedding_type][grid_param] = fs
        del fs, grid_param
    gc.collect()
    return ml_dfs


def build_grid(modality, hyperparam_dict, hyperparams, ensembles):
    for ensemble in ensembles:
        try:
            build_hp_dict(ensemble, modality, hyperparam_dict, hyperparams)
        except:
            print(f"Failed to parse ensemble {ensemble}...")

    if "rsn" in hyperparam_dict.keys():
        hyperparam_dict["rsn"] = [i for i in hyperparam_dict["rsn"] if "res"
                                  not in i]

    hyperparam_dict = OrderedDict(sorted(hyperparam_dict.items(),
                                         key=lambda x: x[0]))
    grid = list(
        itertools.product(*(hyperparam_dict[param] for param in
                            hyperparam_dict.keys()))
    )

    return hyperparam_dict, grid


def get_index_labels(base_dir, ID, ses, modality, grid_param, emb_shape):
    import ast

    node_files = glob.glob(
        f"{base_dir}/embeddings_all_{modality}/sub-{ID}/ses-{ses}/rsn-"
        f"{grid_param[-2]}_res-{grid_param[-3]}/nodes/*.json")

    if len(node_files) > 0:
        ixs, node_dict = parse_closest_ixs(node_files, emb_shape)
    else:
        return [None]

    # Correct labels/index if needed
    if isinstance(node_dict, list):
        if all(v is None for v in [i['label'] for i in node_dict]):
            node_dict_revised = {}
            for i in range(len(node_dict)):
                node_dict_revised[i] = {}
                node_dict_revised[i]['label'], node_dict_revised[i][
                    'index'] = ast.literal_eval(
                    node_dict[i]['index'].replace('\n', ','))
            ixs = [i['index'] for i in node_dict_revised.values()]
        else:
            ixs = [i['index'] for i in node_dict]

    else:
        ixs = [i['index'] for i in node_dict.values()]

    if emb_shape == len(ixs):
        return ixs
    else:
        return [None]


def node_files_search(node_files, emb_shape):
    import ast
    import json

    if len(node_files) == 1:
        with open(node_files[0],
                  'r+') as f:
            node_dict = json.load(f)
        if isinstance(node_dict, list):
            if all(v is None for v in
                   [i['label'] for i in node_dict]):
                node_dict_revised = {}
                for i in range(len(node_dict)):
                    node_dict_revised[i] = {}
                    node_dict_revised[i]['label'], \
                    node_dict_revised[i][
                        'index'] = ast.literal_eval(
                        node_dict[i]['index'].replace('\n', ','))
                ixs_corr = [int(i['index']) for i in
                            node_dict_revised.values()]
            else:
                ixs_corr = [int(i['index'])
                            for i
                            in node_dict]
        else:
            ixs_corr = [int(i['index'])
                        for i
                        in node_dict.values()]
    else:
        try:
            with open(node_files[0],
                      'r+') as f:
                node_dict = json.load(
                    f)
            j = 0
        except:
            with open(node_files[1], 'r+') as f:
                node_dict = json.load(f)
            j = 1

        if isinstance(node_dict, list):
            if all(v is None for v in
                   [i['label'] for i in node_dict]):
                node_dict_revised = {}
                for i in range(len(node_dict)):
                    node_dict_revised[i] = {}
                    node_dict_revised[i]['label'], \
                    node_dict_revised[i][
                        'index'] = ast.literal_eval(
                        node_dict[i]['index'].replace('\n', ','))
                ixs_corr = [int(k['index']) for k in
                            node_dict_revised.values()]
            else:
                ixs_corr = [int(i['index'])
                            for i
                            in node_dict]
        else:
            ixs_corr = [int(i['index'])
                        for i
                        in node_dict.values()]

        while len(ixs_corr) != emb_shape and j < len(
            node_files):
            try:
                with open(node_files[j],
                          'r+') as f:
                    node_dict = json.load(
                        f)
            except:
                j += 1
                continue
            if isinstance(node_dict, list):
                if all(v is None for v in
                       [i['label'] for i in node_dict]):
                    node_dict_revised = {}
                    for i in range(len(node_dict)):
                        node_dict_revised[i] = {}
                        node_dict_revised[i]['label'], \
                        node_dict_revised[i][
                            'index'] = ast.literal_eval(
                            node_dict[i]['index'].replace('\n', ','))
                    ixs_corr = [int(i['index']) for i in
                                node_dict_revised.values()]
                else:
                    ixs_corr = [int(i['index'])
                                for i
                                in node_dict]
            else:
                ixs_corr = [int(i['index'])
                            for i
                            in node_dict.values()]
            j += 1

    return ixs_corr, node_dict


def parse_closest_ixs(node_files, emb_shape):
    if len(node_files) > 0:
        node_files_named = [i for i in node_files if
                      f"{emb_shape}" in i]
        if len(node_files_named) > 0:
            ixs_corr, node_dict = node_files_search(node_files_named, emb_shape)
        else:
            ixs_corr, node_dict = node_files_search(node_files, emb_shape)
        return ixs_corr, node_dict
    else:
        print(UserWarning('Node files empty!'))
        return [], {}


def flatten_latent_positions(base_dir, subject_dict, ID, ses, modality,
                             grid_param, alg):

    if grid_param in subject_dict[ID][str(ses)][modality][alg].keys():
        rsn_dict = subject_dict[ID][str(ses)][modality][alg][grid_param]

        if 'data' in rsn_dict.keys():
            ixs = [i for i in rsn_dict['index'] if i is not None]

            if not isinstance(rsn_dict["data"], np.ndarray):
                data_path = rsn_dict["data"]
                rsn_dict["data"] = np.load(data_path)

            emb_shape = rsn_dict["data"].shape[0]

            if len(ixs) != emb_shape:
                node_files = glob.glob(
                    f"{base_dir}/embeddings_all_{modality}/sub-{ID}/ses-{ses}/rsn-{grid_param[-2]}_res-{grid_param[-3]}/nodes/*.json")
                ixs, node_dict = parse_closest_ixs(node_files, emb_shape)

            if len(ixs) > 0:
                if len(ixs) == emb_shape:
                    rsn_arr = rsn_dict["data"].T.reshape(
                        1, rsn_dict["data"].T.shape[0] * rsn_dict["data"].T.shape[1]
                    )
                    if rsn_dict["data"].shape[1] == 1:
                        df_lps = pd.DataFrame(rsn_arr, columns=[f"{i}_rsn-{grid_param[-2]}_res-{grid_param[-3]}_dim1"
                                                                for i in ixs])
                    elif rsn_dict["data"].shape[1] == 3:
                        df_lps = pd.DataFrame(
                            rsn_arr,
                            columns=[f"{i}_rsn-{grid_param[-2]}_res-{grid_param[-3]}_dim1" for i in ixs]
                            + [f"{i}_rsn-{grid_param[-2]}_res-{grid_param[-3]}_dim2" for i in ixs]
                            + [f"{i}_rsn-{grid_param[-2]}_res-{grid_param[-3]}_dim3" for i in ixs],
                        )
                    else:
                        df_lps = None
                    # else:
                    #     raise ValueError(
                    #         f"Number of dimensions {rsn_dict['data'].shape[1]} "
                    #         f"not supported. See flatten_latent_positions "
                    #         f"function..."
                    #     )
                    # print(df_lps)
                else:
                    print(
                        f"Length of indices {len(ixs)} does not equal the "
                        f"number of rows {rsn_dict['data'].shape[0]} in the "
                        f"embedding-space for {ID} {ses} {modality} "
                        f"{grid_param}. This means that at some point a"
                        f" node index was dropped from the parcellation, but "
                        f"not from the final graph..."
                    )
                    df_lps = None
            else:
                print(UserWarning(f"Missing indices for {grid_param} universe..."))
                df_lps = None
        else:
            print(UserWarning(f"Missing {grid_param} universe..."))
            df_lps = None
    else:
        print(UserWarning(f"Missing {grid_param} universe..."))
        df_lps = None

    return df_lps


def create_feature_space(base_dir, df, grid_param, subject_dict, ses,
                         modality, alg, mets=None):
    df_tmps = []

    for ID in df["participant_id"]:
        if ID not in subject_dict.keys():
            print(f"ID: {ID} not found...")
            continue

        if str(ses) not in subject_dict[ID].keys():
            print(f"Session: {ses} not found for ID {ID}...")
            continue

        if modality not in subject_dict[ID][str(ses)].keys():
            print(f"Modality: {modality} not found for ID {ID}, "
                  f"ses-{ses}...")
            continue

        if alg not in subject_dict[ID][str(ses)][modality].keys():
            print(
                f"Modality: {modality} not found for ID {ID}, ses-{ses}, "
                f"{alg}..."
            )
            continue

        if alg == "OMNI" or alg == "ASE":
            df_lps = flatten_latent_positions(
                base_dir, subject_dict, ID, ses, modality, grid_param, alg
            )
        else:
            if grid_param in subject_dict[ID][str(ses)][modality][alg].keys():
                df_lps = pd.DataFrame(
                    subject_dict[ID][str(ses)][modality][alg][grid_param].T,
                    columns=mets,
                )
            else:
                df_lps = None

        if df_lps is not None:
            df_tmp = (
                df[df["participant_id"] == ID]
                .reset_index()
                .drop(columns="index")
                .join(df_lps, how="right")
            )
            df_tmps.append(df_tmp)
            del df_tmp
        else:
            print(f"Feature-space null for ID {ID} & ses-{ses}, modality: "
                  f"{modality}, embedding: {alg}...")
            continue

    if len(df_tmps) > 0:
        dfs = [dff.set_index("participant_id"
                             ) for dff in df_tmps if not dff.empty]
        df_all = pd.concat(dfs, axis=0)
        df_all = df_all.replace({0: np.nan})
        # df_all = df_all.apply(lambda x: np.where(x < 0.00001, np.nan, x))
        #print(len(df_all))
        del df_tmps
        return df_all, grid_param
    else:
        return pd.Series(np.nan), grid_param


def graph_theory_prep(df, thr_type, drop_thr=0.50):
    from sklearn.impute import KNNImputer
    from sklearn.preprocessing import MinMaxScaler
    cols = [
        j
        for j in set(
            [i.split("_thrtype-" + thr_type + "_")[0] for i in
             list(set(df.columns))]
        )
        if j != "id"
    ]

    id_col = df["id"]

    df = df.dropna(thresh=len(df) * drop_thr, axis=1)
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    scaler = MinMaxScaler(feature_range=(0, 1))
    imp = KNNImputer(n_neighbors=7)
    df = pd.DataFrame(
        imp.fit_transform(scaler.fit_transform(df[[i for i in
                                                   df.columns if i != "id"]])),
        columns=[i for i in df.columns if i != "id"],
    )

    df = pd.concat([id_col, df], axis=1)

    return df, cols


def make_subject_dict(
    modalities, base_dir, thr_type, mets, embedding_types, template, sessions,
    rsns):
    from joblib import Parallel, delayed
    from pynets.core.utils import mergedicts
    import tempfile
    import psutil
    import shutil
    import gc

    hyperparams_func = ["rsn", "res", "model", "hpass", "extract", "smooth"]
    hyperparams_dwi = ["rsn", "res", "model", "directget", "minlength", "tol"]

    miss_frames_all = []
    subject_dict_all = {}
    modality_grids = {}
    for modality in modalities:
        print(f"MODALITY: {modality}")
        hyperparams = eval(f"hyperparams_{modality}")
        for alg in embedding_types:
            print(f"EMBEDDING TYPE: {alg}")
            for ses_name in sessions:
                if alg == "ASE" or alg == "OMNI":
                    ids = [
                        f"{os.path.basename(i)}_ses-{ses_name}"
                        for i in
                        glob.glob(f"{base_dir}/embeddings_all_{modality}/*")
                        if os.path.basename(i).startswith("sub")
                    ]
                else:
                    ids = [
                        f"{os.path.basename(i)}_ses-{ses_name}"
                        for i in glob.glob(f"{base_dir}/pynets/*")
                        if os.path.basename(i).startswith("sub")
                    ]

                if alg == "ASE" or alg == "OMNI":
                    df_top = None
                    ensembles = get_ensembles_embedding(modality, alg,
                                                        base_dir)
                    if ensembles is None:
                        print("No ensembles found.")
                        continue
                elif alg == "topology":
                    ensembles, df_top = get_ensembles_top(
                        modality, thr_type, f"{base_dir}/pynets"
                    )
                    if "missing" in df_top.columns:
                        df_top.drop(columns="missing", inplace=True)

                    if ensembles is None or df_top is None:
                        print("Missing topology outputs.")
                        continue
                else:
                    continue

                ensembles = list(set([i for i in ensembles if i is not None]))

                hyperparam_dict = {}

                grid = build_grid(
                    modality, hyperparam_dict, sorted(list(set(hyperparams))),
                    ensembles)[1]

                grid = list(set([i for i in grid if i != () and
                                 len(list(i)) > 0]))

                # In the case that we are using all of the 3 RSN connectomes
                # (pDMN, coSN, and fECN) in the feature-space,
                # rather than varying them as hyperparameters (i.e. we assume
                # they each add distinct variance
                # from one another) Create an abridged grid, where

                modality_grids[modality] = grid

                par_dict = subject_dict_all.copy()
                cache_dir = tempfile.mkdtemp()

                with Parallel(
                    n_jobs=len(ids),
                    backend='loky',
                    verbose=1,
                    max_nbytes=f"{int(float(list(psutil.virtual_memory())[4]/len(ids)))}M",
                    temp_folder=cache_dir,
                ) as parallel:
                    outs_tup = parallel(
                        delayed(populate_subject_dict)(
                            id,
                            modality,
                            grid,
                            par_dict,
                            alg,
                            base_dir,
                            template,
                            thr_type,
                            mets,
                            df_top,
                        )
                        for id in ids
                    )
                del par_dict
                gc.collect()
                outs = [i[0] for i in outs_tup]
                miss_frames = [i[1] for i in outs_tup if not i[1].empty]
                del outs_tup
                if len(miss_frames) > 1:
                    miss_frames = pd.concat(miss_frames)
                miss_frames_all.append(miss_frames)
                for d in outs:
                    subject_dict_all = dict(mergedicts(subject_dict_all, d))
                del outs, df_top, miss_frames
                gc.collect()
                shutil.rmtree(cache_dir, ignore_errors=True)
            del ses_name, grid, hyperparam_dict
            gc.collect()
        del alg, hyperparams
        gc.collect()
    del modality
    gc.collect()

    return subject_dict_all, modality_grids, miss_frames_all


def populate_subject_dict(
    id,
    modality,
    grid,
    subject_dict,
    alg,
    base_dir,
    template,
    thr_type,
    mets=None,
    df_top=None,
):
    from colorama import Fore, Style
    from joblib import Parallel, delayed
    import gc

    # print(id)
    ID = id.split("_")[0].split("sub-")[1]
    ses = id.split("_")[1].split("ses-")[1]

    completion_status = f"{Fore.GREEN}✓{Style.RESET_ALL}"

    if ID not in subject_dict.keys():
        subject_dict[ID] = {}

    if ses not in subject_dict[ID].keys():
        subject_dict[ID][ses] = {}

    if modality not in subject_dict[ID][ses].keys():
        subject_dict[ID][ses][modality] = {}

    if alg not in subject_dict[ID][ses][modality].keys():
        subject_dict[ID][ses][modality][alg] = {}

    subject_dict[ID][ses][modality][alg] = dict.fromkeys(grid, np.nan)

    missingness_frame = pd.DataFrame(columns=["id", "ses", "modality", "alg",
                                              "grid"])

    # Functional case
    if modality == "func":
        # with Parallel(
        #     n_jobs=4,
        #     require='sharedmem',
        #     verbose=1,
        # ) as parallel:
        #     parallel(
        #         delayed(func_grabber)(comb, subject_dict, missingness_frame,
        #                               ID, ses, modality, alg, mets, thr_type,
        #                               base_dir,
        #                               template,
        #                               df_top)
        #         for comb in grid
        #     )
        for comb in grid:
            [subject_dict, missingness_frame] = func_grabber(comb, subject_dict,
                                                            missingness_frame,
                        ID, ses, modality, alg, mets,
                        thr_type, base_dir, template, df_top)
    # Structural case
    elif modality == "dwi":
        # with Parallel(
        #     n_jobs=4,
        #     require='sharedmem',
        #     verbose=1,
        # ) as parallel:
        #     parallel(
        #         delayed(dwi_grabber)(comb, subject_dict, missingness_frame,
        #                               ID, ses, modality, alg, mets, thr_type,
        #                               base_dir,
        #                               template,
        #                               df_top)
        #         for comb in grid
        #     )
        for comb in grid:
            [subject_dict, missingness_frame] = dwi_grabber(comb, subject_dict,
                                                            missingness_frame,
                        ID, ses, modality, alg, mets,
                        thr_type, base_dir, template, df_top)
    del modality, ID, ses, df_top
    gc.collect()
    return subject_dict, missingness_frame


def dwi_grabber(comb, subject_dict, missingness_frame,
                 ID, ses, modality, alg, mets, thr_type, base_dir, template,
                 df_top):
    from pynets.core.utils import filter_cols_from_targets
    from colorama import Fore, Style
    import gc

    try:
        directget, minlength, model, res, atlas, tol = comb
    except BaseException:
        print(UserWarning(f"{Fore.YELLOW}Failed to parse recipe: "
                          f"{comb}{Style.RESET_ALL}"))
        return subject_dict, missingness_frame

    #comb_tuple = (atlas, directget, minlength, model, res, tol)
    comb_tuple = comb

    # print(comb_tuple)
    subject_dict[ID][ses][modality][alg][comb_tuple] = {}
    if alg == "ASE" or alg == "OMNI":
        embeddings = glob.glob(
            f"{base_dir}/embeddings_all"
            f"_{modality}/sub-{ID}/ses-{ses}/rsn-{atlas}_"
            f"res-{res}/gradient-*")

        embeddings = [i for i in embeddings if (alg in i) and (f"res-{res}" in i) and
                      (f"rsn-{atlas}" in i) and (f"template-{template}" in i) and
                      (f"model-{model}" in i) and (f"directget-{directget}" in i) and
                      (f"minlength-{minlength}" in i) and (f"tol-{tol}" in i)]

        if len(embeddings) == 0:
            print(
                f"{Fore.YELLOW}No structural embeddings found for {ID} and"
                f" recipe {comb_tuple} & {alg}...{Style.RESET_ALL}"
            )
            missingness_frame = missingness_frame.append(
                {
                    "id": ID,
                    "ses": ses,
                    "modality": modality,
                    "alg": alg,
                    "grid": comb_tuple,
                },
                ignore_index=True,
            )
            return subject_dict, missingness_frame
        elif len(embeddings) == 1:
            embedding = embeddings[0]
        else:
            embeddings_raw = [i for i in embeddings if "thrtype" not
                              in i]
            if len(embeddings_raw) == 1:
                embedding = embeddings[0]

            elif len(embeddings_raw) > 1:
                sorted_embeddings = sorted(embeddings_raw,
                                           key=os.path.getmtime)
                print(
                    f"Multiple functional embeddings found for {ID} and"
                    f" recipe {comb_tuple}:\n{embeddings}\nTaking the most"
                    f" recent..."
                )
                embedding = sorted_embeddings[0]
            else:
                sorted_embeddings = sorted(embeddings,
                                           key=os.path.getmtime)
                print(
                    f"Multiple functional embeddings found for {ID} and"
                    f" recipe {comb_tuple}:\n{embeddings}\nTaking the most"
                    f" recent..."
                )
                embedding = sorted_embeddings[0]

        if os.path.isfile(embedding):
            # print(f"Found {ID}, {ses}, {modality}, {comb_tuple}...")
            try:
                ixs = get_index_labels(base_dir, ID, ses, modality,
                                       comb_tuple, np.load(embedding).shape[0])
            except BaseException:
                print(f"{Fore.YELLOW}Failed to load {embedding} for {ID}-{ses}{Style.RESET_ALL}")
                return subject_dict, missingness_frame

            if (
                alg
                not in subject_dict[ID][ses][modality][alg][
                comb_tuple].keys()
            ):
                subject_dict[ID][ses][modality][alg][comb_tuple] = {}
            subject_dict[ID][ses][modality][alg][comb_tuple]["index"] = ixs
            # subject_dict[ID][ses][modality][alg][comb_tuple]["labels"] = labels
            subject_dict[ID][ses][modality][alg][comb_tuple][
                "data"] = embedding
            # print(data)
            completion_status = f"{Fore.GREEN}✓{Style.RESET_ALL}"
            print(
                f"ID: {ID}, SESSION: {ses}, COMPLETENESS: {completion_status}")
        else:
            print(
                f"{Fore.YELLOW}Structural embedding not found for {ID} and"
                f" recipe {comb_tuple} & {alg}...{Style.RESET_ALL}"
            )
            missingness_frame = missingness_frame.append(
                {
                    "id": ID,
                    "ses": ses,
                    "modality": modality,
                    "alg": alg,
                    "grid": comb_tuple,
                },
                ignore_index=True,
            )
            return subject_dict, missingness_frame
    elif alg == "topology":
        data = np.empty([len(mets), 1], dtype=np.float32)
        data[:] = np.nan
        targets = [
            f"minlength-{minlength}",
            f"directget-{directget}",
            f"model-{model}",
            f"res-{res}",
            f"rsn-{atlas}",
            f"tol-{tol}",
            f"thrtype-{thr_type}",
        ]

        cols = filter_cols_from_targets(df_top, targets)
        i = 0
        for met in mets:
            col_met = [j for j in cols if met in j]
            if len(col_met) == 1:
                col = col_met[0]
            elif len(col_met) > 1:
                print(f"Multiple columns detected: {col_met}")
                col = col_met[0]
            else:
                print(
                    f"Structural topology not found for {ID}, "
                    f"{met}, and recipe {comb_tuple}..."
                )
                data[i] = np.nan
                i += 1
                missingness_frame = missingness_frame.append(
                    {
                        "id": ID,
                        "ses": ses,
                        "modality": modality,
                        "alg": alg,
                        "grid": comb_tuple,
                    },
                    ignore_index=True,
                )
                print(f"{Fore.YELLOW}Missing metric {met} for ID: {ID}, "
                      f"SESSION: {ses}{Style.RESET_ALL}")
                continue
            out = df_top[df_top["id"] == "sub-" + ID + "_ses-" + ses][
                col
            ].values
            if len(out) == 0:
                print(
                    f"Structural topology not found for {ID}, "
                    f"{met}, and recipe {comb_tuple}..."
                )
                data[i] = np.nan
            else:
                data[i] = out

            del col, out
            i += 1
        if (np.abs(data) < 0.0000001).all():
            data[:] = np.nan
            completion_status = f"{Fore.RED}X{Style.RESET_ALL}"
            print(
                f"ID: {ID}, SESSION: {ses}, COMPLETENESS: {completion_status}")
        elif (np.abs(data) < 0.0000001).any():
            data[data < 0.0000001] = np.nan
            completion_status = f"{Fore.ORANGE}X{Style.RESET_ALL}"
            print(
                f"ID: {ID}, SESSION: {ses}, COMPLETENESS: {completion_status}")
        subject_dict[ID][ses][modality][alg][comb_tuple] = data
        # print(data)
    del comb, comb_tuple
    gc.collect()

    return subject_dict, missingness_frame


def func_grabber(comb, subject_dict, missingness_frame,
                 ID, ses, modality, alg, mets, thr_type, base_dir, template,
                 df_top):
    from pynets.core.utils import filter_cols_from_targets
    from colorama import Fore, Style
    import gc

    try:
        extract, hpass, model, res, atlas, smooth = comb
    except:
        try:
            extract, hpass, model, res, atlas = comb
            smooth = "0"
        except BaseException:
            print(UserWarning(f"{Fore.YELLOW}Failed to parse recipe: "
                              f"{comb}{Style.RESET_ALL}"))
            return subject_dict, missingness_frame
    # comb_tuple = (atlas, extract, hpass, model, res, str(smooth))
    comb_tuple = comb

    # print(comb_tuple)
    subject_dict[ID][ses][modality][alg][comb_tuple] = {}
    if alg == "ASE" or alg == "OMNI":
        embeddings = glob.glob(
            f"{base_dir}/embeddings_all"
            f"_{modality}/sub-{ID}/ses-{ses}/rsn-{atlas}_"
            f"res-{res}/gradient-*")

        embeddings = [i for i in embeddings if (alg in i) and (res in i) and
                      (atlas in i) and (template in i) and (f"model-{model}" in i)
                      and (f"hpass-{hpass}" in i) and (f"extract-{extract}" in i)]

        if smooth == "0":
            embeddings = [
                i
                for i in embeddings
                if "smooth" not in i
            ]
        else:
            embeddings = [
                i
                for i in embeddings
                if f"smooth-{smooth}fwhm" in i
            ]
        if len(embeddings) == 0:
            print(
                f"{Fore.YELLOW}No functional embeddings found for {ID} and"
                f" recipe {comb_tuple} & {alg}...{Style.RESET_ALL}"
            )
            missingness_frame = missingness_frame.append(
                {
                    "id": ID,
                    "ses": ses,
                    "modality": modality,
                    "alg": alg,
                    "grid": comb_tuple,
                },
                ignore_index=True,
            )
            return subject_dict, missingness_frame

        elif len(embeddings) == 1:
            embedding = embeddings[0]
        else:
            embeddings_raw = [i for i in embeddings if "thrtype"
                              not in i]
            if len(embeddings_raw) == 1:
                embedding = embeddings[0]

            elif len(embeddings_raw) > 1:
                sorted_embeddings = sorted(embeddings_raw,
                                           key=os.path.getmtime)
                print(
                    f"Multiple functional embeddings found for {ID} and"
                    f" recipe {comb_tuple}:\n{embeddings}\nTaking the most"
                    f" recent..."
                )
                embedding = sorted_embeddings[0]
            else:
                sorted_embeddings = sorted(embeddings, key=os.path.getmtime)
                print(
                    f"Multiple functional embeddings found for {ID} and"
                    f" recipe {comb_tuple}:\n{embeddings}\nTaking the most"
                    f" recent..."
                )
                embedding = sorted_embeddings[0]

        if os.path.isfile(embedding):
            # print(f"Found {ID}, {ses}, {modality}, {comb_tuple}...")
            try:
                ixs = get_index_labels(base_dir, ID, ses, modality,
                                       comb_tuple, np.load(embedding).shape[0])
            except BaseException:
                print(f"{Fore.YELLOW}Failed to load {embedding} for {ID}-{ses}{Style.RESET_ALL}")
                return subject_dict, missingness_frame
            if (
                alg
                not in subject_dict[ID][ses][modality][alg][comb_tuple].keys()
            ):
                subject_dict[ID][ses][modality][alg][comb_tuple] = {}
            subject_dict[ID][ses][modality][alg][comb_tuple]["index"] = ixs
            # subject_dict[ID][ses][modality][alg][comb_tuple]["labels"] = labels
            subject_dict[ID][ses][modality][alg][comb_tuple][
                "data"] = embedding
            # print(data)
            completion_status = f"{Fore.GREEN}✓{Style.RESET_ALL}"
        else:
            print(
                f"{Fore.YELLOW}Functional embedding not found for {ID} and"
                f" recipe {comb_tuple} & {alg}...{Style.RESET_ALL}"
            )
            missingness_frame = missingness_frame.append(
                {
                    "id": ID,
                    "ses": ses,
                    "modality": modality,
                    "alg": alg,
                    "grid": comb_tuple,
                },
                ignore_index=True,
            )
            return subject_dict, missingness_frame

    elif alg == "topology":
        data = np.empty([len(mets), 1], dtype=np.float32)
        data[:] = np.nan
        if smooth == '0':
            targets = [
                f"extract-{extract}",
                f"hpass-{hpass}Hz",
                f"model-{model}",
                f"res-{res}",
                f"rsn-{atlas}",
                f"thrtype-{thr_type}",
            ]
        else:
            targets = [
                f"extract-{extract}",
                f"hpass-{hpass}Hz",
                f"model-{model}",
                f"res-{res}",
                f"rsn-{atlas}",
                f"smooth-{smooth}fwhm",
                f"thrtype-{thr_type}",
            ]

        cols = filter_cols_from_targets(df_top, targets)
        i = 0
        for met in mets:
            col_met = [j for j in cols if met in j]
            if len(col_met) == 1:
                col = col_met[0]
            elif len(col_met) > 1:
                if comb_tuple[-1] == '0':
                    col = [i for i in col_met if "fwhm" not in i][0]
                else:
                    print(f"Multiple columns detected: {col_met}")
                    col = col_met[0]
            else:
                data[i] = np.nan
                i += 1
                missingness_frame = missingness_frame.append(
                    {
                        "id": ID,
                        "ses": ses,
                        "modality": modality,
                        "alg": alg,
                        "grid": comb_tuple,
                    },
                    ignore_index=True,
                )
                print(f"{Fore.YELLOW}Missing metric {met} for ID: {ID}, SESSION: {ses}{Style.RESET_ALL}")
                continue
            out = df_top[df_top["id"] == f"sub-{ID}_ses-{ses}"][col].values
            if len(out) == 0:
                print(
                    f"Functional topology not found for {ID}, {met}, "
                    f"and recipe {comb_tuple}..."
                )
                data[i] = np.nan
            else:
                data[i] = out

            del col, out
            i += 1
        if (np.abs(data) < 0.0000001).all():
            data[:] = np.nan
            completion_status = f"{Fore.RED}X{Style.RESET_ALL}"
            print(
                f"ID: {ID}, SESSION: {ses}, COMPLETENESS: {completion_status}")
        elif (np.abs(data) < 0.0000001).any():
            data[data < 0.0000001] = np.nan
            completion_status = f"{Fore.ORANGE}X{Style.RESET_ALL}"
            print(
                f"ID: {ID}, SESSION: {ses}, COMPLETENESS: {completion_status}")
        subject_dict[ID][ses][modality][alg][comb_tuple] = data
        # print(data)
    del comb, comb_tuple
    gc.collect()

    return subject_dict, missingness_frame


def cleanNullTerms(d):
    clean = {}
    for k, v in d.items():
        if isinstance(v, dict):
            nested = cleanNullTerms(v)
            if len(nested.keys()) > 0:
                clean[k] = nested
        elif v is not None and v is not np.nan and not isinstance(v, pd.Series):
            clean[k] = v
    return clean


def gen_sub_vec(base_dir, sub_dict_clean, ID, modality, alg, comb_tuple):
    vects = []
    for ses in sub_dict_clean[ID].keys():
        #print(ses)
        if comb_tuple in sub_dict_clean[ID][ses][modality][alg].keys():
            if alg == 'topology':
                vect = sub_dict_clean[ID][ses][modality][alg][comb_tuple]
            else:
                vect = flatten_latent_positions(base_dir, sub_dict_clean, ID,
                                                ses, modality, comb_tuple, alg)
            vects.append(vect)
    vects = [i for i in vects if i is not None and not np.isnan(np.array(i)).all()]
    if len(vects) > 0 and alg == 'topology':
        out = np.concatenate(vects, axis=1)
    elif len(vects) > 0:
        out = pd.concat(vects, axis=0)
        del vects
    else:
        out = None
    #print(out)
    return out


def tuple_insert(tup, pos, ele):
    tup = tup[:pos] + (ele,) + tup[pos:]
    return tup


def build_hp_dict(file_renamed, modality, hyperparam_dict, hyperparams):
    """
    A function to build a hyperparameter dictionary by parsing a given
    file path.
    """

    for hyperparam in hyperparams:
        if (
            hyperparam != "smooth"
            and hyperparam != "hpass"
            and hyperparam != "track_type"
            and hyperparam != "directget"
            and hyperparam != "tol"
            and hyperparam != "minlength"
            and hyperparam != "samples"
            and hyperparam != "nodetype"
            and hyperparam != "template"
            and hyperparam != "extract"

        ):
            if hyperparam not in hyperparam_dict.keys():
                hyperparam_dict[hyperparam] = [
                    str(file_renamed.split(hyperparam + "-")[1].split("_")[0])
                ]
            else:
                hyperparam_dict[hyperparam].append(
                    str(file_renamed.split(hyperparam + "-")[1].split("_")[0])
                )

    if modality == "func":
        if "smooth-" in file_renamed:
            if "smooth" not in hyperparam_dict.keys():
                hyperparam_dict["smooth"] = [str(file_renamed.split(
                    "smooth-")[1].split("_")[0].split("fwhm")[0])]
            else:
                hyperparam_dict["smooth"].append(str(file_renamed.split(
                    "smooth-")[1].split("_")[0].split("fwhm")[0]))
        else:
            if 'smooth' not in hyperparam_dict.keys():
                hyperparam_dict['smooth'] = [str(0)]
            hyperparam_dict["smooth"].append(str(0))
            hyperparams.append("smooth")
        if "hpass-" in file_renamed:
            if "hpass" not in hyperparam_dict.keys():
                hyperparam_dict["hpass"] = [str(file_renamed.split(
                    "hpass-")[1].split("_")[0].split("Hz")[0])]
            else:
                hyperparam_dict["hpass"].append(
                    str(file_renamed.split("hpass-"
                                       )[1].split("_")[0].split("Hz")[0]))
            hyperparams.append("hpass")
        if "extract-" in file_renamed:
            if "extract" not in hyperparam_dict.keys():
                hyperparam_dict["extract"] = [
                    str(file_renamed.split("extract-")[1].split("_")[0])
                ]
            else:
                hyperparam_dict["extract"].append(
                    str(file_renamed.split("extract-")[1].split("_")[0])
                )
            hyperparams.append("extract")

    elif modality == "dwi":
        if "directget-" in file_renamed:
            if "directget" not in hyperparam_dict.keys():
                hyperparam_dict["directget"] = [
                    str(file_renamed.split("directget-")[1].split("_")[0])
                ]
            else:
                hyperparam_dict["directget"].append(
                    str(file_renamed.split("directget-")[1].split("_")[0])
                )
            hyperparams.append("directget")
        if "minlength-" in file_renamed:
            if "minlength" not in hyperparam_dict.keys():
                hyperparam_dict["minlength"] = [
                    str(file_renamed.split("minlength-")[1].split("_")[0])
                ]
            else:
                hyperparam_dict["minlength"].append(
                    str(file_renamed.split("minlength-")[1].split("_")[0])
                )
            hyperparams.append("minlength")
        if "tol-" in file_renamed:
            if "tol" not in hyperparam_dict.keys():
                hyperparam_dict["tol"] = [
                    str(file_renamed.split("tol-")[1].split("_")[0])
                ]
            else:
                hyperparam_dict["tol"].append(
                    str(file_renamed.split("tol-")[1].split("_")[0])
                )
            hyperparams.append("tol")

    for key in hyperparam_dict:
        hyperparam_dict[key] = list(set(hyperparam_dict[key]))

    return hyperparam_dict, hyperparams