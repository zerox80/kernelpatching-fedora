# Synthetic fixture for the RPM adapter; not a real kernel build recipe.
Name: kernel
Summary: Synthetic kernel packaging fixture
Version: 1
Release: 1
License: MIT
Provides: kernel-%{KERNELRELEASE}

%description
Synthetic fixture used to test package metadata transformations.

%if %{with_devel}
%package devel
Summary: Synthetic module development files
AutoReqProv: no
%description -n kernel-devel
Synthetic development package description.
%endif

%post
if [ -x /usr/bin/kernel-install ]; then
    /usr/bin/kernel-install add %{KERNELRELEASE} /lib/modules/%{KERNELRELEASE}/vmlinuz
fi

%preun
/usr/bin/kernel-install remove %{KERNELRELEASE}

%files
/lib/modules/%{KERNELRELEASE}/vmlinuz

%if %{with_devel}
%files devel
/usr/src/kernels/%{KERNELRELEASE}
%endif
