"""
This file holds the functions necessary for merging IDR_stream CP and DP outputs.
As the IDR_stream output follows the pycytominer output format, these merge functions should work for any pycytominer output data.
"""

import pandas as pd
import pathlib
import math
import uuid


def full_loc_map(dp_coord: tuple, cp_image_data_locations: pd.Series) -> tuple:
    """
    helper function for merge_CP_DP_batch_data
    get cp_coord from cp_image_data_locations that is closest to dp_coord

    Parameters
    ----------
    dp_coord : tuple
        dp coord to find closest cp coord for
    cp_image_data_locations : pd.Series
        series of cp coords to get closest one from

    Returns
    -------
    tuple
        closest cp_coord to given dp_coord
    """
    return min(
        cp_image_data_locations,
        key=lambda cp_coord: math.hypot(
            cp_coord[0] - dp_coord[0], cp_coord[1] - dp_coord[1]
        ),
    )


def merge_CP_DP_batch_data(
    cp_batch_data: pd.DataFrame, dp_batch_data: pd.DataFrame, add_cell_uuid: bool = True
) -> pd.DataFrame:
    """
    merge dataframes for IDR_stream output with CP and DP features
    the two features dataframes should have aligned location metadata (plate, well, frame, etc) and the same number of rows (cells)

    Parameters
    ----------
    cp_batch_data : pd.DataFrame
        idrstream_cp batch output
    dp_batch_data : pd.DataFrame
        idrstream_dp batch output
    add_cell_uuid : bool
        whether or not to add a uuid for each cell to the final merged dataframe

    Returns
    -------
    pd.DataFrame
        merged batch data with metadata, CP features, and DP features

    Raises
    ------
    IndexError
        cp and dp dataframes have different number of rows (cells)
    """
    # covert x and y coordiantes to integers
    cp_batch_data[["Location_Center_X", "Location_Center_Y"]] = cp_batch_data[
        ["Location_Center_X", "Location_Center_Y"]
    ].astype(int)
    dp_batch_data[["Location_Center_X", "Location_Center_Y"]] = dp_batch_data[
        ["Location_Center_X", "Location_Center_Y"]
    ].astype(int)

    # check batch data have same number of rows (cells)
    # if batch data have different number of cells, raise an error because they must not have close segmentations
    if cp_batch_data.shape[0] != dp_batch_data.shape[0]:
        raise IndexError("Batch data have different number of rows (cells)!")

    # hide warning for pandas chained assignment
    # this hides the warnings produced by main necessary chained assingments with pandas (can't use .iloc[] for some operations)
    pd.options.mode.chained_assignment = None

    # get cp and dp column names
    cp_columns = cp_batch_data.columns
    dp_columns = dp_batch_data.columns
    # get metadata columns (columns that show up in both dataframes)
    metadata_columns = [col for col in cp_columns if col in dp_columns]

    # remove metadata columns from cp and dp columns
    cp_columns = set(cp_columns) - set(metadata_columns)
    dp_columns = set(dp_columns) - set(metadata_columns)

    # add CP and DP prefixes to their respective columns
    cp_batch_data = cp_batch_data.rename(
        columns={col: f"CP__{col}" for col in cp_columns}
    )
    dp_batch_data = dp_batch_data.rename(
        columns={col: f"DP__{col}" for col in dp_columns}
    )

    # Raise an error if Metadata_DNA not in cp_batch_data
    if "Metadata_DNA" not in cp_batch_data.columns:
        raise IndexError("Metadata_DNA not found in CP batch data!")
    # get each image path because cells within the same image are trying to be associated
    image_paths = cp_batch_data["Metadata_DNA"].unique()

    # list to compile merged dataframes from each image
    compiled_merged_data = []

    # iterate through each image to focus on matching cell positions (x,y)
    for image_path in image_paths:
        # only work with data from the image of interest
        cp_image_data = cp_batch_data.loc[cp_batch_data["Metadata_DNA"] == image_path]
        dp_image_data = dp_batch_data.loc[dp_batch_data["Metadata_DNA"] == image_path]

        # create a location column with x and y coordinates as tuple
        cp_image_data["Full_Location"] = list(
            zip(
                cp_image_data["Location_Center_X"],
                cp_image_data["Location_Center_Y"],
            )
        )
        dp_image_data["Full_Location"] = list(
            zip(
                dp_image_data["Location_Center_X"],
                dp_image_data["Location_Center_Y"],
            )
        )

        # make location for dp match the closest cp location (distance minimized with hypotenuse)
        dp_image_data["Full_Location"] = dp_image_data["Full_Location"].map(
            lambda dp_coord: full_loc_map(dp_coord, cp_image_data["Full_Location"])
        )

        # drop metadata columns from DP before merge
        dp_image_data = dp_image_data.drop(columns=metadata_columns)

        # merge cp and dp data on location
        merged_image_data = pd.merge(cp_image_data, dp_image_data, on="Full_Location")
        # remove of full location column
        merged_image_data = merged_image_data.drop(columns=["Full_Location"])

        # add merged image data to the compilation list
        compiled_merged_data.append(merged_image_data)

    # show warning again (if other methods should be showing this error)
    pd.options.mode.chained_assignment = "warn"

    # compile merged data into one dataframe with concat and reset index for compiled dataframe
    compiled_merged_data = pd.concat(compiled_merged_data).reset_index(drop=True)

    # add cell uuid to merged data to give each cell a unique identifier
    if add_cell_uuid:
        cell_uuids = [uuid.uuid4() for _ in range(compiled_merged_data.shape[0])]
        compiled_merged_data.insert(loc=0, column="Cell_UUID", value=cell_uuids)

    return compiled_merged_data


def save_merged_CP_DP_run(
    cp_data_dir_path: pathlib.Path,
    dp_data_dir_path: pathlib.Path,
    merged_data_dir_path: pathlib.Path,
):
    """
    merge CP and DP IDR_stream outputs into one set of batch files

    Parameters
    ----------
    cp_data_dir_path : pathlib.Path
        path to directory with IDR_stream CP batch output files
    dp_data_dir_path : pathlib.Path
        path to directory with IDR_stream DP batch output files
    merged_data_dir_path : pathlib.Path
        path to directory to save merged batch output files
    """

    # create merged data directory if it doesn't already exist
    merged_data_dir_path.mkdir(parents=True, exist_ok=True)

    # iterate through all batch files in cp data directory
    for cp_batch_data_path in sorted(cp_data_dir_path.iterdir()):
        # load cp batch data
        cp_batch_data = pd.read_csv(
            cp_batch_data_path,
            compression="gzip",
            index_col=0,
        )
        # load dp batch data
        dp_batch_data_path = pathlib.Path(
            f"{dp_data_dir_path}/{cp_batch_data_path.name}"
        )
        dp_batch_data = pd.read_csv(
            dp_batch_data_path,
            compression="gzip",
            index_col=0,
        )

        # get merged batch data
        merged_batch_data = merge_CP_DP_batch_data(cp_batch_data, dp_batch_data)

        # save merged batch data
        merged_batch_data_path = pathlib.Path(
            f"{merged_data_dir_path}/{cp_batch_data_path.name}"
        )
        merged_batch_data.to_csv(merged_batch_data_path, compression="gzip")
