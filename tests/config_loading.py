#!/usr/bin/env python3

import filecmp
import pytest
from pathlib import Path
from spim_core.config_base import Config, SpimConfig


def test_load_from_yaml():
    this_dir = Path(__file__).parent.resolve() # directory of this test file.
    config_path = this_dir / Path("test_configs/config.yaml")
    Config(str(config_path))

def test_load_from_toml():
    this_dir = Path(__file__).parent.resolve() # directory of this test file.
    config_path = this_dir / Path("test_configs/config.toml")
    Config(str(config_path))

def test_save_valid_filetypes():
    """Ensure we can
        (1) load a yaml and save a yaml and
        (1) load a toml and save a toml"""
    for ext in ["yaml", "toml"]:
        this_dir = Path(__file__).parent.resolve() # directory of this test file.
        config_dir = this_dir / Path("test_configs")
        config_path = this_dir / Path(f"test_configs/config.{ext}")
        new_config_path = this_dir / Path(f"test_configs/config_output.{ext}")
        try:
            cfg = Config(str(config_path))
            cfg.save(str(new_config_path))
        finally:
            new_config_path.unlink() # delete the file we made

def test_load_toml_saveas_yaml():
    """Load a toml. Save it as a yaml."""
    this_dir = Path(__file__).parent.resolve() # directory of this test file.
    config_dir = this_dir / Path("test_configs")
    config_path = this_dir / Path("test_configs/config.toml")
    new_config_path = this_dir / Path("test_configs/config_output.yaml")
    try:
        cfg = Config(str(config_path))
        cfg.save(str(new_config_path))
    finally:
        new_config_path.unlink() # delete the file we made

def test_save_wrong_filetype():
    """Try to save a file with the wrong file extension."""
    this_dir = Path(__file__).parent.resolve() # directory of this test file.
    config_path = this_dir / Path("test_configs/config.yaml")
    cfg = Config(str(config_path))
    new_config_path = this_dir / Path("test_configs/config_output.toast")
    with pytest.raises(ValueError):
        cfg.save(str(new_config_path))

def test_preserve_yaml_order_and_comments():
    """Load a valid yaml file with comments in it. Save it to a new file.
       Diff both files to make sure comments were preserved.
       Delete the file we made."""
    # Note: this yaml file has comments in it.
    this_dir = Path(__file__).parent.resolve() # directory of this test file.
    config_dir = this_dir / Path("test_configs")
    config_path = this_dir / Path("test_configs/config.yaml")
    new_config_path = this_dir / Path("test_configs/config_output.yaml")
    files_match = False
    try:
        cfg = Config(str(config_path))
        cfg.save(str(new_config_path))
        files_match = filecmp.cmp(str(config_path), str(new_config_path))
    finally:
        new_config_path.unlink() # delete the file we made
    assert files_match


def test_spim_config_from_yaml():
    this_dir = Path(__file__).parent.resolve() # directory of this test file.
    config_path = this_dir / Path("test_configs/config.yaml")
    SpimConfig(str(config_path))

def test_spim_config_member_access_from_yaml():
    """Access various members from an existing config with valid data."""
    this_dir = Path(__file__).parent.resolve() # directory of this test file.
    config_path = this_dir / Path("test_configs/config.yaml")
    cfg = SpimConfig(str(config_path))
    # Test accessing various values.
    assert cfg.column_count_px == 14192
    assert cfg.x_voxel_size_um == 0.748
    assert cfg.image_dtype == "uint16"

def test_spim_config_member_writing_from_yaml():
    """Change members from an existing config with valid data."""
    this_dir = Path(__file__).parent.resolve() # directory of this test file.
    config_path = this_dir / Path("test_configs/config.yaml")
    cfg = SpimConfig(str(config_path))
    # Test accessing various values.
    cfg.image_dtype = "uint32"
    assert cfg.image_dtype == "uint32"
    # don't save this config.
