#[cfg(windows)]
mod platform {
    use std::env;
    use std::mem::{size_of, zeroed};
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;

    use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, JOB_OBJECT_LIMIT_PROCESS_MEMORY,
    };

    pub(crate) struct ProcessGuard {
        job: HANDLE,
    }

    impl ProcessGuard {
        pub(crate) fn attach(child: &Child) -> Result<Self, String> {
            let memory_limit = env::var("PHOENIX_OBSCURA_MAX_RSS_BYTES")
                .ok()
                .and_then(|value| value.parse::<usize>().ok())
                .unwrap_or(512 * 1024 * 1024)
                .clamp(64 * 1024 * 1024, 2 * 1024 * 1024 * 1024);
            unsafe {
                let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
                if job.is_null() {
                    return Err(last_error("CreateJobObjectW"));
                }
                let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = zeroed();
                limits.BasicLimitInformation.LimitFlags =
                    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_PROCESS_MEMORY;
                limits.ProcessMemoryLimit = memory_limit;
                let configured = SetInformationJobObject(
                    job,
                    JobObjectExtendedLimitInformation,
                    (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
                    size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                );
                if configured == 0 {
                    let error = last_error("SetInformationJobObject");
                    CloseHandle(job);
                    return Err(error);
                }
                let process = child.as_raw_handle() as HANDLE;
                if AssignProcessToJobObject(job, process) == 0 {
                    let error = last_error("AssignProcessToJobObject");
                    CloseHandle(job);
                    return Err(error);
                }
                Ok(Self { job })
            }
        }
    }

    impl Drop for ProcessGuard {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.job);
            }
        }
    }

    fn last_error(operation: &str) -> String {
        let code = unsafe { GetLastError() };
        format!("{operation} failed with Windows error {code}")
    }
}

#[cfg(not(windows))]
mod platform {
    use std::process::Child;

    pub(crate) struct ProcessGuard;

    impl ProcessGuard {
        pub(crate) fn attach(_child: &Child) -> Result<Self, String> {
            Ok(Self)
        }
    }
}

pub(crate) use platform::ProcessGuard;
